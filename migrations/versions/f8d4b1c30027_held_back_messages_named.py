"""Name the messages the inbox cannot draw.

Data only, no schema change. A message WhatsApp holds back from business
numbers (its error 131051) arrives as kind ``unsupported`` and still names
what it was: a poll vote, an album's wrapper. The inbox kept only
``{"type": "unsupported"}``; it now keeps that name as ``raw_type`` and the
chat says what the message was. This fills ``raw_type`` in for the ones
already stored, read from the callback each came in, which is kept.

It also turns n8n's earliest stand-in, the text ``[unsupported message]``,
into a message the inbox cannot draw, as the importer already did for n8n's
later one; and rewrites a chat list's second line where it was the general
words and its latest message is now named.

The words are copied here as they were on the day, not imported: the app's
may change, and a migration has to do the same thing every time it runs.

Downgrade leaves the data: older code reads ``extra.type`` and ignores
``raw_type``, and shows the general words, as before.

Revision ID: f8d4b1c30027
Revises: e3c5a9d20026
Create Date: 2026-11-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f8d4b1c30027"
down_revision: Union[str, Sequence[str], None] = "e3c5a9d20026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GENERAL = "A message this inbox cannot show"
WORDS_SQL = """
CASE
  WHEN extra->>'type' = 'unsupported' THEN
    CASE extra->>'raw_type'
      WHEN 'poll_update' THEN 'Voted in a poll (WhatsApp does not share the vote)'
      WHEN 'album' THEN 'Sent an album (its photos show as their own messages)'
      WHEN 'location' THEN 'Shared a location (this inbox cannot show locations yet)'
      WHEN 'contacts' THEN 'Shared a contact (this inbox cannot show contacts yet)'
      WHEN 'order' THEN 'Sent a cart from the catalogue (this inbox cannot show carts yet)'
      ELSE 'Something WhatsApp does not share with this inbox'
    END
  WHEN extra->>'type' = 'poll_update' THEN 'Voted in a poll (WhatsApp does not share the vote)'
  WHEN extra->>'type' = 'album' THEN 'Sent an album (its photos show as their own messages)'
  WHEN extra->>'type' = 'location' THEN 'Shared a location (this inbox cannot show locations yet)'
  WHEN extra->>'type' = 'contacts' THEN 'Shared a contact (this inbox cannot show contacts yet)'
  WHEN extra->>'type' = 'order' THEN 'Sent a cart from the catalogue (this inbox cannot show carts yet)'
  ELSE 'A message this inbox cannot show'
END
"""


def upgrade() -> None:
    # The inbox writes to these tables as messages arrive. Give up after five
    # seconds (and retry the deploy) rather than queue behind a held lock.
    op.execute("SET LOCAL lock_timeout = '5s'")

    # 1. What WhatsApp named each held-back message, from its callback.
    op.execute(
        """
        UPDATE inbox_message m
        SET extra = m.extra || jsonb_build_object('raw_type', left(held.raw_type, 40))
        FROM (
            SELECT DISTINCT ON (msg->>'id') msg->>'id' AS wamid,
                   msg->'unsupported'->>'type' AS raw_type
            FROM meta_webhook_event e,
                 jsonb_path_query(e.payload, '$.entry[*].changes[*].value.messages[*]') AS msg
            WHERE msg->>'type' = 'unsupported'
              AND msg->'unsupported'->>'type' IS NOT NULL
            ORDER BY msg->>'id'
        ) held
        WHERE m.wa_message_id = held.wamid
          AND m.kind = 'unsupported'
          AND m.extra->>'type' = 'unsupported'
          AND NOT (m.extra ? 'raw_type')
        """
    )

    # 2. n8n's earliest stand-in for the same.
    op.execute(
        """
        UPDATE inbox_message
        SET kind = 'unsupported', body = NULL
        WHERE direction = 'in' AND kind = 'text' AND body = '[unsupported message]'
        """
    )

    # 3. The chat list's second line, where its latest message is now named.
    op.execute(
        f"""
        UPDATE inbox_conversation c
        SET last_preview = latest.words
        FROM (
            SELECT DISTINCT ON (conversation_id) conversation_id, kind, {WORDS_SQL} AS words
            FROM inbox_message
            WHERE kind <> 'reaction'
            ORDER BY conversation_id, occurred_at DESC, id DESC
        ) latest
        WHERE latest.conversation_id = c.id
          AND latest.kind = 'unsupported'
          AND c.last_preview IN ('{GENERAL}', '[unsupported message]')
          AND latest.words <> c.last_preview
        """
    )


def downgrade() -> None:
    # Nothing to undo: see the module's note.
    pass
