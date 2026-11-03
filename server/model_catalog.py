"""Server-owned Meta model choices; never accept an endpoint from the browser."""
import os
import re

DEFAULT_MODEL = 'accounts/fireworks/models/muse-spark-open'
# Fireworks model pages checked 2026-10-29. Configuration does not prove access.
# Additional models need an existing deployment; this app never provisions one.
MODELS = (
    ('muse-spark-open', 'Muse Spark Open', 'muse-spark-open', 'META_MODEL_SPARK', True, True),
    ('muse-glimmer-30b', 'Muse Glimmer 30B', 'muse-glimmer-30b', 'META_MODEL_GLIMMER', True, False),
    ('llama4-scout', 'Llama 4 Scout', 'llama4-scout-instruct-basic', 'META_MODEL_LLAMA4_SCOUT', False, False),
    ('llama4-maverick', 'Llama 4 Maverick', 'llama4-maverick-instruct-basic', 'META_MODEL_LLAMA4_MAVERICK', False, False),
    ('llama31-70b', 'Llama 3.1 70B Instruct', 'llama-v3p1-70b-instruct', 'META_MODEL_LLAMA31_70B', False, False),
)
DEPLOYMENT = r'accounts/[A-Za-z0-9_-]+/deployments/[A-Za-z0-9_-]+'
META_MODELS = (
    ('muse-spark-1.3', 'Muse Spark 1.3', 'text'),
    ('muse-wonder-1.0', 'Muse Wonder', 'text'),
    ('muse-image-1.0', 'Muse Image', 'image'),
)


class ModelSelectionError(ValueError):
    pass


def catalog():
    choices = []
    for key, label, slug, variable, reasoning, serverless in MODELS:
        base = 'accounts/fireworks/models/' + slug
        endpoint = os.getenv(variable, '').strip() or (base if serverless else '')
        valid = bool(endpoint) and ((serverless and endpoint == base) or bool(re.fullmatch(DEPLOYMENT, endpoint))
            or bool(re.fullmatch(re.escape(base) + '#' + DEPLOYMENT, endpoint)))
        choices.append({'id': key, 'label': label, 'base_model': base, 'endpoint': endpoint,
                        'provider': 'fireworks', 'modality': 'text',
                        'configured': valid and bool(os.getenv('META_API_KEY', '').strip()),
                        'reasoning_supported': reasoning, 'enabled': valid,
                        'availability': 'configured' if valid else 'invalid_configuration' if endpoint else 'requires_deployment'})
    for key, label, modality in META_MODELS:
        configured = bool(os.getenv('MODEL_API_KEY', '').strip())
        choices.append({'id': key, 'label': label, 'base_model': key, 'endpoint': key,
                        'provider': 'meta', 'modality': modality, 'configured': configured,
                        'reasoning_supported': modality == 'text', 'enabled': True,
                        'availability': 'key_configured_access_unverified' if configured else 'requires_meta_key'})
    return choices


def default_id():
    configured = os.getenv('META_MODEL', DEFAULT_MODEL).strip()
    for row in catalog():
        if configured and configured in (row['id'], row['base_model'], row['endpoint']):
            return row['id']
    raise ModelSelectionError('meta_model_not_allowed')


def resolve(model_id=None):
    selected = default_id() if model_id is None else model_id
    row = next((row for row in catalog() if row['id'] == selected), None)
    if row is None:
        raise ModelSelectionError('meta_model_not_allowed')
    if not row['enabled']:
        raise ModelSelectionError('meta_model_setup_required')
    return row


def public_catalog():
    return [{key: value for key, value in row.items() if key != 'endpoint'}
            for row in catalog() if row['enabled']]
