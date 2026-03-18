"""Tests for task completion protocol handler."""

from unittest.mock import MagicMock, patch

import pytest

from extend_lab_intake.protocols.task_completion import TaskCompletionHandler
from extend_lab_intake.utils.constants import Labels, Secrets


class TestTaskCompletionHandler:
    """Tests for TaskCompletionHandler."""

    @pytest.fixture
    def mock_task(self) -> MagicMock:
        """Create a mock task."""
        task = MagicMock()
        task.id = "task-123"
        task.status = "COMPLETED"
        task.title = "Lab Intake: test_report.pdf"
        task.patient_id = "patient-456"
        task.created = MagicMock()
        task.created.isoformat.return_value = "2024-01-15T10:00:00Z"
        task.modified = MagicMock()
        task.modified.isoformat.return_value = "2024-01-15T10:30:00Z"

        # Mock labels
        mock_label = MagicMock()
        mock_label.name = Labels.LAB_INTAKE
        task.labels = [mock_label]

        return task

    @pytest.fixture
    def handler(self) -> TaskCompletionHandler:
        """Create a TaskCompletionHandler instance."""
        mock_event = MagicMock()
        mock_event.target.id = "task-123"

        handler = TaskCompletionHandler(event=mock_event)
        handler.secrets = {}

        return handler

    def test_is_lab_intake_task_by_label(
        self, handler: TaskCompletionHandler, mock_task: MagicMock
    ) -> None:
        """Test task identification by label."""
        assert handler._is_lab_intake_task(mock_task) is True

    def test_is_lab_intake_task_by_title(
        self, handler: TaskCompletionHandler
    ) -> None:
        """Test task identification by title fallback."""
        task = MagicMock()
        task.labels = []
        task.title = "Lab Intake: some_file.pdf"

        assert handler._is_lab_intake_task(task) is True

    def test_is_not_lab_intake_task(self, handler: TaskCompletionHandler) -> None:
        """Test non-lab-intake task is not matched."""
        task = MagicMock()
        task.labels = []
        task.title = "Follow up with patient"

        assert handler._is_lab_intake_task(task) is False

    def test_build_callback_payload(
        self, handler: TaskCompletionHandler, mock_task: MagicMock
    ) -> None:
        """Test callback payload construction."""
        payload = handler._build_callback_payload(mock_task)

        assert payload["event"] == "lab_intake_completed"
        assert payload["task_id"] == "task-123"
        assert payload["status"] == "COMPLETED"
        assert payload["patient_id"] == "patient-456"
        assert payload["created_at"] == "2024-01-15T10:00:00Z"
        assert payload["completed_at"] == "2024-01-15T10:30:00Z"

    def test_compute_skips_non_completed_task(
        self, handler: TaskCompletionHandler, mock_task: MagicMock
    ) -> None:
        """Test that non-completed tasks are skipped."""
        mock_task.status = "OPEN"

        with patch(
            "canvas_sdk.v1.data.task.Task.objects.get",
            return_value=mock_task,
        ):
            effects = handler.compute()

        assert effects == []

    def test_compute_skips_non_lab_intake_task(
        self, handler: TaskCompletionHandler
    ) -> None:
        """Test that non-lab-intake tasks are skipped."""
        mock_task = MagicMock()
        mock_task.status = "COMPLETED"
        mock_task.labels = []
        mock_task.title = "Regular task"

        with patch(
            "canvas_sdk.v1.data.task.Task.objects.get",
            return_value=mock_task,
        ):
            effects = handler.compute()

        assert effects == []

    def test_compute_sends_callback_on_completion(
        self, handler: TaskCompletionHandler, mock_task: MagicMock
    ) -> None:
        """Test that callback is sent when task is completed."""
        handler.secrets = {Secrets.CALLBACK_URL: "https://callback.example.com"}

        # Mock the prefetch_related chain
        mock_queryset = MagicMock()
        mock_queryset.get.return_value = mock_task

        with patch(
            "extend_lab_intake.protocols.task_completion.Task.objects.prefetch_related",
            return_value=mock_queryset,
        ), patch.object(handler, "_send_callback") as mock_send:
            effects = handler.compute()

        mock_send.assert_called_once()

    def test_compute_no_callback_without_url(
        self, handler: TaskCompletionHandler, mock_task: MagicMock
    ) -> None:
        """Test that no callback sent when URL not configured."""
        handler.secrets = {}  # No callback URL

        # Mock the prefetch_related chain
        mock_queryset = MagicMock()
        mock_queryset.get.return_value = mock_task

        with patch(
            "extend_lab_intake.protocols.task_completion.Task.objects.prefetch_related",
            return_value=mock_queryset,
        ), patch.object(handler, "_send_callback") as mock_send:
            effects = handler.compute()

        mock_send.assert_not_called()

    @patch("requests.post")
    def test_send_callback_success(
        self,
        mock_post: MagicMock,
        handler: TaskCompletionHandler,
        mock_task: MagicMock,
    ) -> None:
        """Test successful callback sending."""
        mock_post.return_value = MagicMock(status_code=200)

        handler._send_callback("https://callback.example.com", mock_task)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args.kwargs["json"]["event"] == "lab_intake_completed"

    @patch("requests.post")
    def test_send_callback_non_success_status(
        self,
        mock_post: MagicMock,
        handler: TaskCompletionHandler,
        mock_task: MagicMock,
    ) -> None:
        """Test callback with non-success status."""
        mock_post.return_value = MagicMock(status_code=500, text="Server error")

        # Should not raise exception
        handler._send_callback("https://callback.example.com", mock_task)

        mock_post.assert_called_once()

    @patch("requests.post")
    def test_send_callback_exception(
        self,
        mock_post: MagicMock,
        handler: TaskCompletionHandler,
        mock_task: MagicMock,
    ) -> None:
        """Test callback handles request exception."""
        mock_post.side_effect = Exception("Network error")

        # Should not raise exception
        handler._send_callback("https://callback.example.com", mock_task)

    def test_build_callback_payload_with_comments(
        self, handler: TaskCompletionHandler, mock_task: MagicMock
    ) -> None:
        """Test payload includes summary from comments."""
        mock_comment = MagicMock()
        mock_comment.body = "Lab Results Summary: All values normal"
        mock_task.comments.all.return_value = [mock_comment]

        payload = handler._build_callback_payload(mock_task)

        assert payload["summary"] == "Lab Results Summary: All values normal"

    def test_build_callback_payload_no_comments(
        self, handler: TaskCompletionHandler, mock_task: MagicMock
    ) -> None:
        """Test payload without comments."""
        mock_task.comments.all.return_value = []

        payload = handler._build_callback_payload(mock_task)

        assert "summary" not in payload

    def test_build_callback_payload_comments_exception(
        self, handler: TaskCompletionHandler, mock_task: MagicMock
    ) -> None:
        """Test payload handles comments exception."""
        del mock_task.comments  # Remove comments attribute

        # Should not raise exception
        payload = handler._build_callback_payload(mock_task)

        assert "summary" not in payload
