DELETE FROM settings
WHERE key IN (
    'ai.global',
    'credential.ai.api_key',
    'credential.longbridge.app_key',
    'credential.longbridge.app_secret',
    'credential.longbridge.access_token'
);

UPDATE settings
SET value_json = json_remove(
    value_json,
    '$.ai_base_url',
    '$.ai_model',
    '$.timeout_seconds',
    '$.max_retries'
)
WHERE key = 'services.config';

DROP TABLE setting_credentials;
DROP TABLE credential_artifacts;
