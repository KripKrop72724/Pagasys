import logging
from celery import shared_task
from django.utils import timezone

from .models import PunchEvent

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def finalize_punch(self, punch_id: int) -> None:
    """Perform final punch validation asynchronously."""
    ev = PunchEvent.objects.filter(id=punch_id).first()
    if not ev:
        return
    try:
        ev.processed = True
        ev.processed_at = timezone.now()
        ev.save(update_fields=["processed", "processed_at"])
    except Exception as exc:  # pragma: no cover
        logger.exception("finalize_punch failed")
        raise self.retry(exc=exc)
