"""Hosted image comparisons. No generated code or untrusted URLs run."""
import asyncio
import base64
import hashlib
import io
import json
import time
from typing import Literal
from uuid import UUID

import httpx
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import meta_ai

MAX_UPLOAD = 4 * 1024 * 1024
MAX_PIXELS = 4_000_000
MAX_OUTPUT = 8 * 1024 * 1024
MAX_ASSETS = 24 * 1024 * 1024


class MediaRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    model: Literal['muse-image-1.0']
    action: Literal['generate', 'edit']
    prompt: str = Field(min_length=1, max_length=4000)
    image: str | None = Field(default=None, max_length=5_600_000)

    @model_validator(mode='after')
    def valid_action(self):
        if not self.prompt.strip():
            raise ValueError('Enter a request.')
        if self.action != 'generate' and not self.image:
            raise ValueError('Upload an image first.')
        if self.action == 'generate' and self.image:
            raise ValueError('Use Edit image to provide a reference image.')
        return self


def png(image):
    out = io.BytesIO()
    image.save(out, format='PNG')
    value = out.getvalue()
    if len(value) > MAX_OUTPUT:
        raise meta_ai.AIError('media_output_too_large')
    return value


def read_image(raw, *, upload=False):
    if len(raw) > (MAX_UPLOAD if upload else MAX_OUTPUT):
        raise meta_ai.AIError('media_image_too_large')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP') or getattr(source, 'n_frames', 1) != 1:
                raise ValueError('Unsupported image')
            w, h = source.size
            if w * h > (MAX_PIXELS if upload else 16_000_000) or max(w, h) > (4096 if upload else 8192):
                raise ValueError('Image dimensions exceed limits')
            source.load()
            return ImageOps.exif_transpose(source).convert('RGBA' if 'A' in source.getbands() else 'RGB')
    except Exception:
        raise meta_ai.AIError('media_invalid_image') from None


def upload_image(value):
    if value is None:
        return None
    try:
        header, payload = value.split(',', 1)
        if header not in ('data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64'):
            raise ValueError('Invalid type')
        raw = base64.b64decode(payload, validate=True)
    except Exception:
        raise meta_ai.AIError('media_invalid_image') from None
    return png(read_image(raw, upload=True))


def data_url(raw):
    return 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')


async def bounded_json(client, url, headers, body):
    async with client.stream('POST', url, headers=headers, json=body) as response:
        if response.status_code >= 300:
            raise meta_ai.AIError(meta_ai.provider_error(response.status_code), provider_status=response.status_code)
        value = bytearray()
        async for chunk in response.aiter_bytes():
            value.extend(chunk)
            if len(value) > 12_000_000:
                raise meta_ai.AIError('media_output_too_large')
        try:
            return json.loads(value)
        except (ValueError, UnicodeError):
            raise meta_ai.AIError('meta_format') from None


async def generate(config, action, prompt, raw):
    body = {'model': config.model, 'prompt': prompt, 'n': 1,
            'response_format': 'b64_json', 'output_format': 'png', 'reasoning_strength': 'high'}
    path = '/images/generations'
    if action == 'edit':
        path = '/images/edits'
        body['images'] = [{'image_url': data_url(raw)}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20), follow_redirects=False) as client:
        response = await bounded_json(client, config.base + path, {'Authorization': 'Bearer ' + config.key}, body)
    try:
        data = response['data']
        if len(data) != 1:
            raise ValueError('Unexpected image count')
        image = read_image(base64.b64decode(data[0]['b64_json'], validate=True))
    except (KeyError, TypeError, ValueError):
        raise meta_ai.AIError('meta_format') from None
    return {'image.png': png(image)}, {'usage': response.get('usage'), 'width': image.width, 'height': image.height}


async def prepare_prompt(action, prompt, raw, config):
    instruction = (
        'Rewrite the user request as one clear image generation/editing prompt. Preserve every requested '
        'subject, text string and constraint. Do not add new facts, objects, style or requirements. '
        'For editing, identify the requested change and preserve everything else.'
    )
    content = [{'type': 'text', 'text': prompt}]
    if raw:
        content.append({'type': 'image_url', 'image_url': {'url': data_url(raw)}})
    message, evidence = await meta_ai.complete([
        {'role': 'system', 'content': instruction + ' Return JSON only: {"prompt": "...", "note": "brief explanation"}.'},
        {'role': 'user', 'content': content}], config, json_mode=True, timeout_seconds=80)
    try:
        result = json.loads(message['content'])
        refined = result['prompt'].strip()
        if not refined or len(refined) > 4000:
            raise ValueError('Invalid prompt')
        return refined, {'method': 'model_preparation', 'model': config.label, 'elapsed_ms': evidence['elapsed_ms'],
                         'usage': evidence.get('usage'), 'note': str(result.get('note', ''))[:1000]}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise meta_ai.AIError('media_request_needs_clarification') from None


async def compare(job, publish):
    config, planner = job['_config'], job['_planner_config']
    raw, action, question = job['_media_input'], job['action'], job['question']
    engines = {}
    started = time.perf_counter()
    result = {'mode': 'media', 'action': action, 'model': config.label, 'engines': engines,
              'protocol': {'target_model': config.public(), 'planner_model': planner.public(),
                           'same_input_image_sha256': hashlib.sha256(raw).hexdigest() if raw else None,
                           'image_settings': {'n': 1, 'reasoning_strength': 'high', 'output_format': 'png'},
                           'assisted_method': 'prompt_preparation_then_same_target_model',
                           'optimizer_used': False, 'gpu_execution_verified': False,
                           'quality_automatically_verified': False}, 'complete': False}

    async def arm(name):
        t = time.perf_counter()
        output = {'status': 'running', 'prompt': question, 'model_calls': 0}
        try:
            async with asyncio.timeout(380):
                if name == 'assisted':
                    output['model_calls'] += 1
                    output['prompt'], output['preparation'] = await prepare_prompt(action, question, raw, planner)
                output['model_calls'] += 1
                provider_started = time.perf_counter()
                assets, details = await generate(config, action, output['prompt'], raw)
                output['provider_ms'] = (time.perf_counter() - provider_started) * 1000
                if sum(map(len, assets.values())) + sum(len(v) for v in job['_media_assets'].values()) > MAX_ASSETS:
                    raise meta_ai.AIError('media_output_too_large')
                output['artifacts'] = []
                for filename, value in assets.items():
                    key = name + '-' + filename
                    job['_media_assets'][key] = value
                    prefix = '/api/v1/media/jobs/' if job.get('_channel') == 'api' else '/api/media/jobs/'
                    output['artifacts'].append({'filename': key, 'url': prefix + job['id'] + '/assets/' + key})
                output.update(status='completed', **details)
        except (httpx.TimeoutException, TimeoutError):
            output.update(status='failed', error='meta_timeout')
        except meta_ai.AIError as exc:
            output.update(status='failed', error=str(exc), provider_status=exc.provider_status)
        except Exception:
            output.update(status='failed', error='media_invalid_response')
        finally:
            output['total_ms'] = (time.perf_counter() - t) * 1000
        engines[name] = output
        publish(stage='running', partial={**result, 'engines': dict(engines)})

    async with asyncio.TaskGroup() as group:
        group.create_task(arm('meta'))
        group.create_task(arm('assisted'))
    result.update(complete=True, wall_ms=(time.perf_counter() - started) * 1000)
    a, b = engines['meta'], engines['assisted']
    if a['status'] == b['status'] == 'completed':
        result['comparison'] = {'latency_ratio_meta_over_assisted': a['total_ms'] / max(1, b['total_ms']),
                                'quality_winner': None, 'quality_note': 'Compare the images against your request. Speed alone does not establish quality.'}
    else:
        result['comparison'] = {'latency_ratio_meta_over_assisted': None, 'quality_winner': None,
                                'quality_note': 'A path failed. No latency or quality winner is declared.'}
    return result
