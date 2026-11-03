"""Independent Bearer credentials for server-to-server API clients."""
import hashlib
import hmac
import json
import os
import re
from fastapi import HTTPException

PREFIX = '/api/v1'
PER_MINUTE = 4
PER_DAY = 40
GLOBAL_PER_DAY = 80
READS_PER_MINUTE = 90
JOB_TTL = 3600
MAX_JOBS = 20


def credentials():
    """Read secrets from Render only; never serialize this mapping."""
    keys = {}
    primary = os.getenv('AI_PLUS_API_KEY', '').strip()
    if primary:
        keys['default'] = primary
    extra = os.getenv('AI_PLUS_API_KEYS', '').strip()
    if extra:
        try:
            obj = json.loads(extra)
        except ValueError:
            raise ValueError('api_configuration_invalid') from None
        if not isinstance(obj, dict) or len(obj) > 20 or 'default' in obj:
            raise ValueError('api_configuration_invalid')
        keys.update(obj)
    seen = set()
    for name, token in keys.items():
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', name)
            or not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_+/=-]{32,256}', token)
            or token in seen):
            raise ValueError('api_configuration_invalid')
        seen.add(token)
    return keys


def configuration_status():
    try:
        return 'enabled' if credentials() else 'not_configured'
    except ValueError:
        return 'invalid_configuration'


def authenticate(header):
    try:
        keys = credentials()
    except ValueError:
        raise HTTPException(503, 'api_configuration_invalid') from None
    if not keys:
        raise HTTPException(503, 'api_not_configured')
    scheme, _, candidate = header.partition(' ')
    if scheme.lower() != 'bearer' or not 32 <= len(candidate) <= 256:
        raise HTTPException(401, 'invalid_api_key', headers={'WWW-Authenticate': 'Bearer'})
    candidate_digest = hashlib.sha256(candidate.encode()).digest()
    matched = False
    for token in keys.values():
        matched |= hmac.compare_digest(candidate_digest, hashlib.sha256(token.encode()).digest())
    if not matched:
        raise HTTPException(401, 'invalid_api_key', headers={'WWW-Authenticate': 'Bearer'})
    # Different keys have separate ownership, even if their client labels match.
    return 'api:' + candidate_digest.hex()


def limits():
    return {'new_jobs_per_minute_per_key': PER_MINUTE, 'new_jobs_per_24h_per_key': PER_DAY,
            'new_jobs_per_24h_all_api_keys': GLOBAL_PER_DAY,
            'http_requests_per_minute_per_key': READS_PER_MINUTE,
            'concurrent_jobs_shared_with_website': 1,
            'job_retention_seconds': JOB_TTL, 'max_retained_jobs_shared_with_website': MAX_JOBS,
            'job_timeout_seconds': 400, 'max_request_bytes': 150000,
            'storage': 'Jobs and rate counters are in memory, reset on restart, and require one instance and one worker. These limits are not a billing cap.'}
