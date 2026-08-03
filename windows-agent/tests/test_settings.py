import pytest
from pydantic import ValidationError

from homeguard_agent.config import Settings


def test_remote_mode_requires_credentials(tmp_path):
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, remote_enabled=True)


def test_detector_backend_validation(tmp_path):
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, detector_backend="magic")


def test_normalized_detection_zones_validate(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        detection_zone=(0.1, 0.2, 0.8, 0.7),
        exclusion_zones=[(0.2, 0.2, 0.1, 0.1)],
    )
    assert settings.detection_zone == (0.1, 0.2, 0.8, 0.7)


def test_invalid_detection_zone_rejected(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, detection_zone=(0.8, 0.0, 0.3, 1.0))


def test_remote_mode_requires_uuid_identities(tmp_path):
    with pytest.raises(ValidationError):
        Settings(
            data_dir=tmp_path,
            remote_enabled=True,
            supabase_url="https://project.supabase.co",
            supabase_anon_key="anon",
            supabase_access_token="access",
            owner_id="not-a-uuid",
            device_id="also-not-a-uuid",
        )


def test_remote_uuid_identities_are_accepted(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        remote_enabled=True,
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon",
        supabase_access_token="access",
        owner_id="11111111-1111-4111-8111-111111111111",
        device_id="22222222-2222-4222-8222-222222222222",
    )
    assert settings.remote_enabled is True
