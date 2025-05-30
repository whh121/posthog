from datetime import datetime, timedelta, UTC
import json
from unittest import mock
from unittest.mock import MagicMock, patch
from uuid import uuid4

from boto3 import resource
from botocore.config import Config
from django.db import transaction
from django.test import override_settings
from freezegun import freeze_time
from rest_framework import status

from posthog import redis
from posthog.models import SessionRecording, SessionRecordingPlaylistItem, Team
from posthog.models.user import User
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
    SessionRecordingPlaylistViewed,
)
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.test.base import APIBaseTest

TEST_BUCKET = "test_storage_bucket-ee.TestSessionRecordingPlaylist"


@override_settings(
    OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER=TEST_BUCKET,
    OBJECT_STORAGE_SESSION_RECORDING_LTS_FOLDER=f"{TEST_BUCKET}_lts",
)
class TestSessionRecordingPlaylist(APIBaseTest):
    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

    def _create_playlist(self, data: dict | None = None):
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists",
            data=data,
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response

    def test_list_playlists_when_there_are_no_playlists(self):
        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }

    def test_list_playlists_when_there_are_some_playlists(self):
        playlist_one = self._create_playlist({"name": "test"})
        playlist_two = self._create_playlist({"name": "test2"})

        # set some saved filter counts up
        SessionRecordingViewed.objects.create(
            team=self.team,
            user=self.user,
            session_id="a",
        )
        redis.get_client().set(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist_two.json()['short_id']}",
            json.dumps({"session_ids": ["a", "b"], "has_more": False, "previous_ids": ["b"]}),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "count": 2,
            "next": None,
            "previous": None,
            "results": [
                {
                    "created_at": mock.ANY,
                    "created_by": {
                        "distinct_id": self.user.distinct_id,
                        "email": self.user.email,
                        "first_name": "",
                        "hedgehog_config": None,
                        "id": self.user.id,
                        "is_email_verified": None,
                        "last_name": "",
                        "role_at_organization": None,
                        "uuid": mock.ANY,
                    },
                    "deleted": False,
                    "derived_name": None,
                    "description": "",
                    "filters": {},
                    "id": playlist_two.json()["id"],
                    "last_modified_at": mock.ANY,
                    "last_modified_by": {
                        "distinct_id": self.user.distinct_id,
                        "email": self.user.email,
                        "first_name": "",
                        "hedgehog_config": None,
                        "id": self.user.id,
                        "is_email_verified": None,
                        "last_name": "",
                        "role_at_organization": None,
                        "uuid": mock.ANY,
                    },
                    "name": "test2",
                    "pinned": False,
                    "recordings_counts": {
                        "collection": {
                            "count": None,
                            "watched_count": 0,
                        },
                        "saved_filters": {
                            "count": 2,
                            "has_more": False,
                            "watched_count": 1,
                            "increased": True,
                            "last_refreshed_at": None,
                        },
                    },
                    "short_id": playlist_two.json()["short_id"],
                },
                {
                    "created_at": mock.ANY,
                    "created_by": {
                        "distinct_id": self.user.distinct_id,
                        "email": self.user.email,
                        "first_name": "",
                        "hedgehog_config": None,
                        "id": self.user.id,
                        "is_email_verified": None,
                        "last_name": "",
                        "role_at_organization": None,
                        "uuid": mock.ANY,
                    },
                    "deleted": False,
                    "derived_name": None,
                    "description": "",
                    "filters": {},
                    "id": playlist_one.json()["id"],
                    "last_modified_at": mock.ANY,
                    "last_modified_by": {
                        "distinct_id": self.user.distinct_id,
                        "email": self.user.email,
                        "first_name": "",
                        "hedgehog_config": None,
                        "id": self.user.id,
                        "is_email_verified": None,
                        "last_name": "",
                        "role_at_organization": None,
                        "uuid": mock.ANY,
                    },
                    "name": "test",
                    "pinned": False,
                    "recordings_counts": {
                        "collection": {
                            "count": None,
                            "watched_count": 0,
                        },
                        "saved_filters": {
                            "count": None,
                            "has_more": None,
                            "watched_count": None,
                            "increased": None,
                            "last_refreshed_at": None,
                        },
                    },
                    "short_id": playlist_one.json()["short_id"],
                },
            ],
        }

    def test_creates_playlist(self):
        response = self._create_playlist({"name": "test"})

        assert response.json() == {
            "id": response.json()["id"],
            "short_id": response.json()["short_id"],
            "name": "test",
            "derived_name": None,
            "description": "",
            "pinned": False,
            "created_at": mock.ANY,
            "created_by": response.json()["created_by"],
            "deleted": False,
            "filters": {},
            "last_modified_at": mock.ANY,
            "last_modified_by": response.json()["last_modified_by"],
            "recordings_counts": {
                "collection": {
                    "count": None,
                    "watched_count": 0,
                },
                "saved_filters": {
                    "count": None,
                    "has_more": None,
                    "watched_count": None,
                    "increased": None,
                    "last_refreshed_at": None,
                },
            },
        }

    def test_can_create_many_playlists(self):
        for i in range(100):
            self._create_playlist({"name": f"test-{i}"})

    def test_gets_individual_playlist_by_shortid(self):
        create_response = self._create_playlist()

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{create_response.json()['short_id']}"
        )

        assert response.json()["short_id"] == create_response.json()["short_id"]

    def test_marks_playlist_as_viewed(self):
        create_response = self._create_playlist({"filters": {"events": [{"id": "test"}]}})
        short_id = create_response.json()["short_id"]

        assert SessionRecordingPlaylistViewed.objects.count() == 0

        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert SessionRecordingPlaylistViewed.objects.count() == 1
        viewed_record = SessionRecordingPlaylistViewed.objects.first()
        assert viewed_record is not None

        assert viewed_record.playlist_id == create_response.json()["id"]
        assert viewed_record.user_id == self.user.id
        assert viewed_record.team_id == self.team.id
        assert viewed_record.viewed_at == mock.ANY

    def test_can_marks_playlist_as_viewed_more_than_once(self):
        create_response = self._create_playlist({"filters": {"events": [{"id": "test"}]}})
        short_id = create_response.json()["short_id"]

        assert SessionRecordingPlaylistViewed.objects.count() == 0

        response_one = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )
        assert response_one.status_code == status.HTTP_200_OK
        response_two = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )
        assert response_two.status_code == status.HTTP_200_OK
        assert SessionRecordingPlaylistViewed.objects.count() == 2

    def test_cannot_mark_playlist_as_viewed_more_than_once_at_the_same_time(self):
        create_response = self._create_playlist({"filters": {"events": [{"id": "test"}]}})
        short_id = create_response.json()["short_id"]

        assert SessionRecordingPlaylistViewed.objects.count() == 0

        with freeze_time("2022-01-02"):
            response_one = self.client.post(
                f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
            )
            assert response_one.status_code == status.HTTP_200_OK
            assert SessionRecordingPlaylistViewed.objects.count() == 1

            # Run the API call in a separate atomic block so it doesn't break the main test transaction
            with transaction.atomic():
                response_two = self.client.post(
                    f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
                )
                assert response_two.status_code == status.HTTP_200_OK

        assert SessionRecordingPlaylistViewed.objects.count() == 1

    def test_cannot_mark_playlist_as_viewed_if_it_has_no_filters(self):
        """We're going to split playlists so that 'collections' have pinned recordings, let's validate a viewable playlist as one with filters"""
        create_response = self._create_playlist()
        short_id = create_response.json()["short_id"]

        assert SessionRecordingPlaylistViewed.objects.count() == 0

        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert SessionRecordingPlaylistViewed.objects.count() == 0

    def test_cannot_mark_playlist_as_viewed_in_different_team(self):
        create_response = self._create_playlist({"filters": {"events": [{"id": "test"}]}})
        short_id = create_response.json()["short_id"]

        another_team = Team.objects.create(organization=self.organization)

        response = self.client.post(
            f"/api/projects/{another_team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SessionRecordingPlaylistViewed.objects.count() == 0

    def test_updates_playlist(self):
        create_response = self._create_playlist()
        short_id = create_response.json()["short_id"]

        with freeze_time("2022-01-02"):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
                {
                    "name": "changed name",
                    "description": "changed description",
                    "filters": {"events": [{"id": "test"}]},
                    "pinned": True,
                },
            )

        assert response.json()["short_id"] == short_id
        assert response.json()["name"] == "changed name"
        assert response.json()["description"] == "changed description"
        assert response.json()["filters"] == {"events": [{"id": "test"}]}
        assert response.json()["created_at"] == mock.ANY
        assert response.json()["last_modified_at"] == "2022-01-02T00:00:00Z"

    def test_rejects_updates_to_readonly_playlist_properties(self):
        create_response = self._create_playlist()
        short_id = create_response.json()["short_id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
            {"short_id": "something else", "pinned": True},
        )

        assert response.json()["short_id"] == short_id
        assert response.json()["pinned"]

    def test_filters_based_on_params(self):
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        playlist1 = SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user)
        playlist2 = SessionRecordingPlaylist.objects.create(team=self.team, pinned=True, created_by=self.user)
        playlist3 = SessionRecordingPlaylist.objects.create(team=self.team, name="my playlist", created_by=other_user)

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?search=my",
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]

        assert len(results) == 1
        assert results[0]["short_id"] == playlist3.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?search=playlist",
        ).json()["results"]

        assert len(results) == 2
        assert results[0]["short_id"] == playlist3.short_id
        assert results[1]["short_id"] == playlist1.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?user=true",
        ).json()["results"]

        assert len(results) == 2
        assert results[0]["short_id"] == playlist2.short_id
        assert results[1]["short_id"] == playlist1.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?pinned=true",
        ).json()["results"]

        assert len(results) == 1
        assert results[0]["short_id"] == playlist2.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?created_by={other_user.id}",
        ).json()["results"]

        assert len(results) == 1
        assert results[0]["short_id"] == playlist3.short_id

    def test_filters_saved_filters_type(self):
        # Create a playlist with pinned recordings and no filters
        playlist1 = SessionRecordingPlaylist.objects.create(team=self.team, name="pinned only", created_by=self.user)
        recording1 = SessionRecording.objects.create(team=self.team, session_id=str(uuid4()))
        SessionRecordingPlaylistItem.objects.create(playlist=playlist1, recording=recording1)

        # Create a playlist with both pinned recordings and filters
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="pinned and filters",
            created_by=self.user,
            filters={"events": [{"id": "test"}]},
        )
        recording2 = SessionRecording.objects.create(team=self.team, session_id=str(uuid4()))
        SessionRecordingPlaylistItem.objects.create(playlist=playlist2, recording=recording2)

        # Create a playlist with only filters
        playlist3 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="filters only",
            created_by=self.user,
            filters={"events": [{"id": "test"}]},
        )

        # Create a playlist with only deleted pinned items
        playlist4 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="deleted pinned only",
            created_by=self.user,
        )
        recording4 = SessionRecording.objects.create(team=self.team, session_id=str(uuid4()))
        SessionRecordingPlaylistItem.objects.create(playlist=playlist4, recording=recording4)
        SessionRecordingPlaylistItem.objects.filter(playlist=playlist4, recording=recording4).update(deleted=True)

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?type=saved_filters",
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]

        # Should only return the playlist with filters and no pinned recordings
        # since playlist 4 only has deleted pinned items, then it technically has no pinned
        # so counts has having 0 pinned items
        # but it also has no filters, so it should not be included
        assert [r["name"] for r in results] == [playlist3.name]

    @patch("ee.session_recordings.session_recording_extensions.object_storage.copy_objects")
    def test_get_pinned_recordings_for_playlist(self, mock_copy_objects: MagicMock) -> None:
        mock_copy_objects.return_value = 2

        playlist = SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user)

        session_one = f"test_fetch_playlist_recordings-session1-{uuid4()}"
        session_two = f"test_fetch_playlist_recordings-session2-{uuid4()}"
        three_days_ago = (datetime.now() - timedelta(days=3)).replace(tzinfo=UTC)

        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_one,
            distinct_id="123",
            first_timestamp=three_days_ago,
            last_timestamp=three_days_ago,
        )

        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_two,
            distinct_id="123",
            first_timestamp=three_days_ago,
            last_timestamp=three_days_ago,
        )

        # Create playlist items
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{session_one}"
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{session_two}"
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/session-missing"
        )

        # Test get recordings
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings"
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()

        assert len(result["results"]) == 2
        assert {x["id"] for x in result["results"]} == {session_one, session_two}

    @patch("ee.session_recordings.session_recording_extensions.object_storage.list_objects")
    @patch("ee.session_recordings.session_recording_extensions.object_storage.copy_objects")
    def test_fetch_playlist_recordings(self, mock_copy_objects: MagicMock, mock_list_objects: MagicMock) -> None:
        # all sessions have been blob ingested and had data to copy into the LTS storage location
        mock_copy_objects.return_value = 1

        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist1",
            created_by=self.user,
        )
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist2",
            created_by=self.user,
        )

        session_one = f"test_fetch_playlist_recordings-session1-{uuid4()}"
        session_two = f"test_fetch_playlist_recordings-session2-{uuid4()}"
        three_days_ago = (datetime.now() - timedelta(days=3)).replace(tzinfo=UTC)

        for session_id in [session_one, session_two]:
            produce_replay_summary(
                team_id=self.team.id,
                session_id=session_id,
                distinct_id="123",
                first_timestamp=three_days_ago,
                last_timestamp=three_days_ago,
            )

        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{session_one}",
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{session_two}",
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{session_one}",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings",
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()

        assert len(result["results"]) == 2
        assert result["results"][0]["id"] == session_one
        assert result["results"][1]["id"] == session_two

        # Test get recordings
        result = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings",
        ).json()

        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == session_one

    def test_add_remove_static_playlist_items(self):
        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist1",
            created_by=self.user,
        )
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist2",
            created_by=self.user,
        )

        recording1_session_id = "1"
        recording2_session_id = "2"

        # Add recording 1 to playlist 1
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording1_session_id}",
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist1.id, session_id=recording1_session_id
        )
        assert playlist_item is not None

        # Add recording 2 to playlist 1
        result = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist1.id, session_id=recording2_session_id
        )
        assert playlist_item is not None

        # Add recording 2 to playlist 2
        result = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist2.id, session_id=recording2_session_id
        )
        assert playlist_item is not None

        session_recording_obj_1 = SessionRecording.get_or_build(team=self.team, session_id=recording1_session_id)
        assert session_recording_obj_1

        session_recording_obj_2 = SessionRecording.get_or_build(team=self.team, session_id=recording2_session_id)
        assert session_recording_obj_2

        # Delete playlist items
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording1_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist1.id, session_id=recording1_session_id
            ).count()
            == 0
        )
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist1.id, session_id=recording2_session_id
            ).count()
            == 0
        )
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist2.id, session_id=recording1_session_id
            ).count()
            == 0
        )
