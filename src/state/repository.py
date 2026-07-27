from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def connect(db_path: str | Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=check_same_thread,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_FILE.read_text()
    conn.executescript(sql)
    _ensure_quota_script_id_column(conn)


def _ensure_quota_script_id_column(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(quota_usage)").fetchall()}
    if "script_id" not in cols:
        conn.execute("ALTER TABLE quota_usage ADD COLUMN script_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quota_script_id ON quota_usage(script_id)"
    )


class Repository:
    """Thin DAL. Each stage uses the methods relevant to it; no ORM."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def tx(self) -> Iterator["Repository"]:
        """Transaction context. Yields repo itself — callers use repo methods inside."""
        try:
            self.conn.execute("BEGIN")
            yield self
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # ---- videos ----

    def upsert_video(self, **fields) -> None:
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        update_clause = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "video_id")
        self.conn.execute(
            f"INSERT INTO videos ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(video_id) DO UPDATE SET {update_clause}, updated_at=datetime('now')",
            fields,
        )

    def set_video_status(self, video_id: str, status: str, reason: str | None = None) -> None:
        self.conn.execute(
            "UPDATE videos SET status=?, rejection_reason=?, updated_at=datetime('now') WHERE video_id=?",
            (status, reason, video_id),
        )

    def videos_by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM videos WHERE status=?", (status,)).fetchall()

    def videos_with_statuses(self, statuses: list[str]) -> list[sqlite3.Row]:
        if not statuses:
            return []
        placeholders = ",".join("?" * len(statuses))
        return self.conn.execute(
            f"SELECT * FROM videos WHERE status IN ({placeholders})",
            tuple(statuses),
        ).fetchall()

    def get_video(self, video_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM videos WHERE video_id=?", (video_id,)
        ).fetchone()

    def videos_for_download(self) -> list[sqlite3.Row]:
        """Discovered candidates ordered for the downloader.

        Highest virality score first so the best material lands when budget is tight.
        Stable secondary order (`video_id ASC`) for deterministic reruns.
        """
        return self.conn.execute(
            "SELECT * FROM videos WHERE status='discovered' "
            "ORDER BY virality_score DESC, video_id ASC"
        ).fetchall()

    def evictable_video_ids(self) -> list[str]:
        """Video IDs whose every derived clip is uploaded; oldest first.

        Excludes videos with zero clips — we can't safely delete a source whose
        derivatives haven't been generated yet, even if status='downloaded'.
        """
        rows = self.conn.execute(
            """
            SELECT v.video_id FROM videos v
            WHERE EXISTS (SELECT 1 FROM clips c WHERE c.video_id = v.video_id)
              AND NOT EXISTS (
                  SELECT 1 FROM clips c
                  WHERE c.video_id = v.video_id AND c.status != 'uploaded'
              )
            ORDER BY v.updated_at ASC
            """
        ).fetchall()
        return [r["video_id"] for r in rows]

    def is_raw_evictable(self, video_id: str) -> bool:
        """Single-method safety check: ≥1 clip AND all clips uploaded.

        Critically returns False for videos with zero clips so a stray call site
        can't accidentally delete a source whose derivatives haven't been made.
        """
        row = self.conn.execute(
            """
            SELECT
                EXISTS(SELECT 1 FROM clips WHERE video_id=:vid) AS has_any,
                NOT EXISTS(
                    SELECT 1 FROM clips WHERE video_id=:vid AND status != 'uploaded'
                ) AS all_uploaded
            """,
            {"vid": video_id},
        ).fetchone()
        return bool(row["has_any"]) and bool(row["all_uploaded"])

    # ---- clips ----

    def insert_clip(self, **fields) -> None:
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        self.conn.execute(
            f"INSERT OR REPLACE INTO clips ({cols}) VALUES ({placeholders})", fields
        )

    def upsert_selector_clip(
        self,
        *,
        clip_id: str,
        video_id: str,
        start_s: float,
        end_s: float,
        hook: str,
        suggested_title: str,
        selection_method: str,
    ) -> None:
        """Selector-owned upsert. Touches only selector columns on conflict.

        Critically does NOT clobber publish_at_utc, publish_slot_local, output_path,
        youtube_video_id, or title_slug — those are populated by Phases 4 (editor),
        5 (uploader), and 6 (slot_planner). A `--force` re-rank on a clip whose
        downstream metadata is already filled must preserve that metadata so we
        don't accidentally erase a scheduled or rendered clip's pointer state.
        """
        self.conn.execute(
            """
            INSERT INTO clips (
                clip_id, video_id, start_s, end_s,
                hook, suggested_title, selection_method, status
            ) VALUES (
                :clip_id, :video_id, :start_s, :end_s,
                :hook, :suggested_title, :selection_method, 'selected'
            )
            ON CONFLICT(clip_id) DO UPDATE SET
                start_s          = excluded.start_s,
                end_s            = excluded.end_s,
                hook             = excluded.hook,
                suggested_title  = excluded.suggested_title,
                selection_method = excluded.selection_method,
                status           = 'selected',
                rejection_reason = NULL,
                updated_at       = datetime('now')
            """,
            {
                "clip_id": clip_id,
                "video_id": video_id,
                "start_s": float(start_s),
                "end_s": float(end_s),
                "hook": hook,
                "suggested_title": suggested_title,
                "selection_method": selection_method,
            },
        )

    def set_clip_status(
        self,
        clip_id: str,
        status: str,
        reason: str | None = None,
        **extra,
    ) -> None:
        sets = ["status=?", "rejection_reason=?", "updated_at=datetime('now')"]
        params: list = [status, reason]
        for k, v in extra.items():
            sets.append(f"{k}=?")
            params.append(v)
        params.append(clip_id)
        self.conn.execute(
            f"UPDATE clips SET {', '.join(sets)} WHERE clip_id=?",
            params,
        )

    def clips_by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM clips WHERE status=?", (status,)).fetchall()

    def clips_for_policy_gate(self) -> list[sqlite3.Row]:
        """Clips ready for the post-select policy gate (Phase 4.5).

        Ordered by clip_id for deterministic batch reruns.
        """
        return self.conn.execute(
            "SELECT * FROM clips WHERE status='selected' ORDER BY clip_id"
        ).fetchall()

    def clips_for_quality_screen(self) -> list[sqlite3.Row]:
        """Clips ready for the post-render quality screen (Phase 4.5).

        Excludes scheduled / uploaded clips so the screen is never run on a
        clip whose downstream pointer state would be invalidated by a flip
        to rejected_quality.
        """
        return self.conn.execute(
            "SELECT * FROM clips WHERE status='rendered' "
            "AND publish_at_utc IS NULL AND youtube_video_id IS NULL "
            "ORDER BY clip_id"
        ).fetchall()

    # ---- uploader (Phase 5) ----

    def clips_for_upload(self) -> list[sqlite3.Row]:
        """Clips ready for the uploader: quality_pass or approved, with a
        scheduled publish_at_utc and no youtube_video_id yet.

        Ordered by publish_at_utc ASC (then clip_id) so the daily upload run
        publishes oldest-slot-first. NULL publish_at_utc clips are excluded
        — they're waiting on slot_planner (Phase 6); the standalone CLI's
        `--clip-id --publish-at` path handles single-clip ad-hoc uploads.
        """
        return self.conn.execute(
            "SELECT * FROM clips "
            "WHERE status IN ('quality_pass', 'approved') "
            "AND publish_at_utc IS NOT NULL "
            "AND youtube_video_id IS NULL "
            "ORDER BY publish_at_utc ASC, clip_id ASC"
        ).fetchall()

    # ---- slot_planner / daily_upload (Phase 6) ----

    def clips_for_slot_planner(self) -> list[sqlite3.Row]:
        """Clips ready for slot allocation: quality_pass with NULL publish_at_utc
        and NULL youtube_video_id.

        Ordered by created_at ASC then clip_id ASC so allocation is
        reproducible across reruns of the same batch (critical for --dry-run
        parity vs. real-mode).

        Approved clips are EXCLUDED — once a clip is approved, the user has
        vouched for that exact artifact. Slot_planner does not re-slot
        approved clips even with --force (per Phase 6 plan).
        """
        return self.conn.execute(
            "SELECT * FROM clips "
            "WHERE status='quality_pass' "
            "AND publish_at_utc IS NULL "
            "AND youtube_video_id IS NULL "
            "ORDER BY created_at ASC, clip_id ASC"
        ).fetchall()

    def clips_for_upload_due(
        self,
        end_of_window_utc_iso_z: str,
        *,
        statuses: tuple[str, ...] = ("quality_pass", "approved"),
    ) -> list[sqlite3.Row]:
        """Clips_for_upload() with an additional `publish_at_utc <= ?` window
        bound and a parameterized status whitelist.

        Caller passes the whitelist based on cfg.human_review:
          - human_review=True  → statuses=("approved",)
          - human_review=False → statuses=("quality_pass", "approved")

        Window semantics: `<=` end-of-today (caller computes in cfg.timezone
        and converts to UTC). Past-due clips ARE included so missed-slot
        recovery works (PC was off / Task Scheduler skipped a day).
        """
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        return self.conn.execute(
            f"SELECT * FROM clips "
            f"WHERE status IN ({placeholders}) "
            f"AND publish_at_utc IS NOT NULL "
            f"AND publish_at_utc <= ? "
            f"AND youtube_video_id IS NULL "
            f"ORDER BY publish_at_utc ASC, clip_id ASC",
            (*statuses, end_of_window_utc_iso_z),
        ).fetchall()

    def get_clip_with_video(self, clip_id: str) -> sqlite3.Row | None:
        """Joined clips + videos row for the templater.

        Returns columns from both tables; aliases the videos columns with a
        v_ prefix (v_video_id, v_title, v_channel, v_keyword) so the caller
        can disambiguate from the clips columns. Returns None if the clip
        doesn't exist (defensive — every clip should have a video).
        """
        return self.conn.execute(
            """
            SELECT
                c.*,
                v.video_id  AS v_video_id,
                v.title     AS v_title,
                v.channel   AS v_channel,
                v.keyword   AS v_keyword
            FROM clips c
            LEFT JOIN videos v ON v.video_id = c.video_id
            WHERE c.clip_id = ?
            """,
            (clip_id,),
        ).fetchone()

    def set_clip_youtube_id(self, clip_id: str, youtube_video_id: str) -> None:
        """Narrow critical-section update: write the YouTube videoId onto the
        clip row WITHOUT touching status. Called by the uploader IMMEDIATELY
        after the API call succeeds (step 10a in the post-upload persistence
        sequence) so the next run cannot double-upload even if the
        subsequent status / uploads-row write fails.

        Caller wraps in repo.tx(). The narrowness of this update is intentional
        — every additional column written here widens the critical section
        between API success and durable DB state.
        """
        self.conn.execute(
            "UPDATE clips SET youtube_video_id=?, updated_at=datetime('now') WHERE clip_id=?",
            (youtube_video_id, clip_id),
        )

    def upsert_upload(
        self,
        clip_id: str,
        youtube_video_id: str,
        publish_at_utc: str,
        quota_units_used: int,
    ) -> None:
        """Insert (or update on conflict) an uploads row.

        Uses explicit ON CONFLICT(clip_id) DO UPDATE rather than
        INSERT OR REPLACE so uploaded_at (the default-on-INSERT timestamp)
        is preserved across retries — REPLACE would silently bump it. PK
        on uploads is clip_id.
        """
        self.conn.execute(
            """
            INSERT INTO uploads (clip_id, youtube_video_id, publish_at_utc, quota_units_used)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(clip_id) DO UPDATE SET
                youtube_video_id = excluded.youtube_video_id,
                publish_at_utc   = excluded.publish_at_utc,
                quota_units_used = excluded.quota_units_used
            """,
            (clip_id, youtube_video_id, publish_at_utc, int(quota_units_used)),
        )

    # ---- dup_hashes (Phase 4.5 quality_screen) ----

    def recent_dup_hashes(self, days: int) -> list[sqlite3.Row]:
        """Returns (clip_id, phash, audio_fp) rows from the last N days.

        Includes clip_id so rejection reasons can name the matching prior
        clip. The 90-day window matches cfg.dedup_lookback_days.
        """
        return self.conn.execute(
            "SELECT clip_id, phash, audio_fp FROM dup_hashes "
            "WHERE created_at >= datetime('now', ?)",
            (f"-{int(days)} days",),
        ).fetchall()

    def insert_dup_hash_rows(
        self,
        rows: list[tuple[str, str, str | None]],
    ) -> None:
        """Bulk-insert dup_hashes rows for a single clip.

        Caller must dedupe the phash list (the schema PK is (clip_id, phash))
        and wrap this call in repo.tx() together with set_clip_status. We use
        INSERT OR IGNORE as a belt-and-suspenders against the rare case where
        two of the five sampled frames produce the same phash.
        """
        if not rows:
            return
        self.conn.executemany(
            "INSERT OR IGNORE INTO dup_hashes (clip_id, phash, audio_fp) "
            "VALUES (?, ?, ?)",
            rows,
        )

    # ---- gameplay rotation: REMOVED in Pivot.3 ----
    # The split-screen + gameplay-rotation editor is gone. The gameplay_cursor
    # and gameplay_pointer tables remain in schema.sql for backward compat
    # with old DBs but no code reads or writes them. They can be dropped by
    # Phase 7 retention's VACUUM pass once we're confident the columns won't
    # be referenced again.

    # ---- discovery: status-preserving upsert ----

    def discovery_upsert_video(
        self,
        *,
        video_id: str,
        title: str,
        channel: str,
        duration_seconds: int,
        views: int,
        likes: int,
        comments: int,
        published_at: str,
        keyword: str,
        virality_score: float,
    ) -> None:
        """Insert a new candidate as 'discovered'; on conflict refresh stats only.

        Critically does NOT touch status, rejection_reason, keyword, or
        discovered_at on existing rows — so a rerun of discovery cannot regress
        a downloaded/uploaded video back to 'discovered'.
        """
        self.conn.execute(
            """
            INSERT INTO videos (
                video_id, title, channel, duration_seconds,
                views, likes, comments, published_at,
                keyword, virality_score, status
            ) VALUES (
                :video_id, :title, :channel, :duration_seconds,
                :views, :likes, :comments, :published_at,
                :keyword, :virality_score, 'discovered'
            )
            ON CONFLICT(video_id) DO UPDATE SET
                title            = excluded.title,
                channel          = excluded.channel,
                duration_seconds = excluded.duration_seconds,
                views            = excluded.views,
                likes            = excluded.likes,
                comments         = excluded.comments,
                virality_score   = excluded.virality_score,
                updated_at       = datetime('now')
            """,
            {
                "video_id": video_id,
                "title": title,
                "channel": channel,
                "duration_seconds": duration_seconds,
                "views": views,
                "likes": likes,
                "comments": comments,
                "published_at": published_at,
                "keyword": keyword,
                "virality_score": virality_score,
            },
        )

    # ---- niche baselines ----

    def historical_views_for_keyword(self, keyword: str, days: int) -> list[int]:
        cutoff = f"-{int(days)} days"
        rows = self.conn.execute(
            "SELECT views FROM videos WHERE keyword=? AND discovered_at >= datetime('now', ?)",
            (keyword, cutoff),
        ).fetchall()
        return [int(r["views"]) for r in rows]

    def niche_median_views(self, keyword: str) -> int:
        row = self.conn.execute(
            "SELECT median_views FROM niche_baselines WHERE keyword=?",
            (keyword,),
        ).fetchone()
        return int(row["median_views"]) if row else 1

    def upsert_niche_baseline(
        self, keyword: str, median_views: int, sample_size: int
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO niche_baselines (keyword, median_views, sample_size)
            VALUES (?, ?, ?)
            ON CONFLICT(keyword) DO UPDATE SET
                median_views = excluded.median_views,
                sample_size  = excluded.sample_size,
                computed_at  = datetime('now')
            """,
            (keyword, int(median_views), int(sample_size)),
        )

    # ---- discovery attempts (idempotency) ----

    def record_discovery_attempt(
        self, keyword: str, inspected_count: int, inserted_count: int
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO discovery_attempts (
                keyword, last_attempted_at, last_inspected, last_inserted
            ) VALUES (?, datetime('now'), ?, ?)
            ON CONFLICT(keyword) DO UPDATE SET
                last_attempted_at = datetime('now'),
                last_inspected    = excluded.last_inspected,
                last_inserted     = excluded.last_inserted
            """,
            (keyword, int(inspected_count), int(inserted_count)),
        )

    def is_in_cooldown(self, keyword: str, hours: int) -> bool:
        cutoff = f"-{int(hours)} hours"
        row = self.conn.execute(
            """
            SELECT 1 FROM discovery_attempts
            WHERE keyword = ?
              AND last_attempted_at > datetime('now', ?)
            """,
            (keyword, cutoff),
        ).fetchone()
        return row is not None

    # ---- runs ----

    def start_run(self, kind: str) -> int:
        cur = self.conn.execute("INSERT INTO runs (kind) VALUES (?)", (kind,))
        return cur.lastrowid

    def finish_run(self, run_id: int, success: bool, summary_json: str) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=datetime('now'), success=?, summary_json=? WHERE run_id=?",
            (1 if success else 0, summary_json, run_id),
        )

    def sweep_abandoned_runs(self, hang_minutes: int) -> list[sqlite3.Row]:
        """Finalize `runs` rows abandoned by a hard process death (Issue 60).

        A row qualifies when `finished_at IS NULL` and `started_at` is older
        than `hang_minutes` ago. Each qualifying row is finalized
        `success=0` with summary `{"message": "abandoned", "started_at": ...}`.

        Callers MUST invoke this only after the cross-process run lock is
        held — a genuinely in-flight run held by another process must never
        be swept out from under it.

        Idempotent: a row already finalized (finished_at set) never matches
        the WHERE clause again, so a second sweep finalizes nothing new.

        Returns the rows that were swept (run_id, kind, started_at), as they
        looked before finalization, so callers can emit one alert per row.
        """
        cutoff = f"-{int(hang_minutes)} minutes"
        rows = self.conn.execute(
            """
            SELECT run_id, kind, started_at FROM runs
            WHERE finished_at IS NULL
              AND started_at < datetime('now', ?)
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            summary_json = json.dumps(
                {"message": "abandoned", "started_at": row["started_at"]}
            )
            self.conn.execute(
                "UPDATE runs SET finished_at=datetime('now'), success=0, "
                "summary_json=? WHERE run_id=?",
                (summary_json, row["run_id"]),
            )
        return rows

    # ---- named single-clip lookup (replaces repo.conn.execute inline SQL) ----

    def get_clip(self, clip_id: str) -> sqlite3.Row | None:
        """Fetch a single clips row by clip_id. Returns None if not found."""
        return self.conn.execute(
            "SELECT * FROM clips WHERE clip_id=?", (clip_id,)
        ).fetchone()

    def clip_has_youtube_id(self, clip_id: str) -> bool:
        """Return True if the clip row has a non-NULL youtube_video_id."""
        row = self.conn.execute(
            "SELECT youtube_video_id FROM clips WHERE clip_id=?", (clip_id,)
        ).fetchone()
        return row is not None and row["youtube_video_id"] is not None

    def set_clip_publish_at(self, clip_id: str, publish_at_utc: str) -> None:
        """Narrow update: write publish_at_utc without touching status."""
        self.conn.execute(
            "UPDATE clips SET publish_at_utc=?, updated_at=datetime('now') WHERE clip_id=?",
            (publish_at_utc, clip_id),
        )

    # ---- quota (absorbed from QuotaLedger) ----

    def quota_record(
        self,
        endpoint: str,
        units: int,
        *,
        provider: str = "youtube",
        script_id: str | None = None,
        recorded_at: str | None = None,
    ) -> None:
        """Record quota usage for today (UTC).

        ``recorded_at`` is normally left to the schema default (``datetime('now')``
        in UTC); tests exercising the rolling-window predicate may pass an
        explicit UTC timestamp (``YYYY-MM-DD HH:MM:SS``) to backdate a row.
        """
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if recorded_at is None:
            self.conn.execute(
                "INSERT INTO quota_usage (date, endpoint, units, provider, script_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (today, endpoint, int(units), provider, script_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO quota_usage "
                "(date, endpoint, units, provider, script_id, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (today, endpoint, int(units), provider, script_id, recorded_at),
            )

    def quota_script_total(self, script_id: str) -> int:
        """Cumulative OpenRouter spend attributed to a script across all dates."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage "
            "WHERE provider='openrouter' AND script_id=?",
            (script_id,),
        ).fetchone()
        return int(row["s"]) if row else 0

    def quota_would_exceed_script(
        self, script_id: str, units: int, ceiling: int,
    ) -> bool:
        """True if recording `units` more would exceed the per-script lifetime ceiling."""
        return (self.quota_script_total(script_id) + units) > ceiling

    def quota_today_total(self, *, provider: str | None = None) -> int:
        """Sum of all units recorded today (UTC), optionally filtered by provider."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if provider is None:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage WHERE date=?",
                (today,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage "
                "WHERE date=? AND provider=?",
                (today, provider),
            ).fetchone()
        return int(row["s"]) if row else 0

    def quota_would_exceed(
        self, units: int, ceiling: int, *, provider: str | None = None,
    ) -> bool:
        """Return True if recording `units` more would push today's total past ceiling."""
        today_total = (
            self.quota_today_total(provider=provider)
            if provider is not None
            else self.quota_today_total()
        )
        return (today_total + units) > ceiling

    def quota_week_total(self, *, provider: str | None = None) -> int:
        """Sum quota units recorded in the last 7 UTC days, optionally by provider."""
        from datetime import datetime, timedelta, timezone

        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=6)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        if provider is None:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage "
                "WHERE date >= ? AND date <= ?",
                (start, end),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage "
                "WHERE date >= ? AND date <= ? AND provider=?",
                (start, end, provider),
            ).fetchone()
        return int(row["s"]) if row else 0

    def quota_rolling_week_total(self, *, provider: str | None = None) -> int:
        """Sum quota units recorded in the rolling 7x24h window ending now.

        Unlike ``quota_week_total`` (calendar-day bucketed on the ``date``
        column), this uses the ``recorded_at`` timestamp so a Sunday run sees
        spend from the previous Sunday onward — a true rolling window, not a
        calendar-week reset.
        """
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        if provider is None:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage "
                "WHERE recorded_at >= ?",
                (cutoff,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage "
                "WHERE recorded_at >= ? AND provider=?",
                (cutoff, provider),
            ).fetchone()
        return int(row["s"]) if row else 0

    def quota_would_exceed_week(
        self, additional_cents: int, ceiling: int, *, provider: str = "openrouter",
    ) -> bool:
        """True if recording `additional_cents` more would push the rolling
        7x24h OpenRouter total past `ceiling`."""
        return (
            self.quota_rolling_week_total(provider=provider) + additional_cents
        ) > ceiling

    def count_topics_by_status(self, status: str) -> int:
        """Count topics rows with the given status."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM topics WHERE status=?",
            (status,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_dashboard_clips(self) -> list[sqlite3.Row]:
        """Clips for the read-only dashboard with optional script metadata."""
        return self.conn.execute(
            """
            SELECT
                c.*,
                s.title        AS script_title,
                s.narration    AS script_narration,
                s.shots_json   AS s_shots_json
            FROM clips c
            LEFT JOIN scripts s ON s.script_id = c.script_id
            WHERE c.content_kind = 'ai_generated'
               OR c.publish_at_utc IS NOT NULL
               OR c.youtube_video_id IS NOT NULL
            ORDER BY c.created_at DESC, c.clip_id ASC
            """
        ).fetchall()

    # ---- Pivot.6: topics ----

    def unscripted_topics(self) -> list[sqlite3.Row]:
        """Return all topics with status='unscripted', oldest first."""
        return self.conn.execute(
            "SELECT * FROM topics WHERE status='unscripted' ORDER BY id ASC"
        ).fetchall()

    def update_topic_score(
        self,
        topic_id: int,
        topic_score_json: str,
        weighted_score: float,
        category: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE topics SET topic_score_json=?, weighted_score=?, category=? WHERE id=?",
            (topic_score_json, weighted_score, category, topic_id),
        )

    def mark_topic_scored(self, topic_id: int) -> None:
        self.conn.execute("UPDATE topics SET status='scored' WHERE id=?", (topic_id,))

    def insert_topic(
        self,
        *,
        url: str,
        title: str,
        source_feed: str,
        fetched_at: str,
        summary: str | None = None,
        published_at: str | None = None,
    ) -> int:
        """Insert a new unscripted topic. Returns the auto-incremented id."""
        cur = self.conn.execute(
            """
            INSERT INTO topics (url, title, summary, source_feed, fetched_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (url, title, summary, source_feed, fetched_at, published_at),
        )
        return cur.lastrowid

    def insert_seen_topic(
        self,
        *,
        url_hash: str,
        title_normalized: str,
        first_seen_at: str,
    ) -> None:
        """Insert a seen_topic row for future dedup. Ignores PK conflicts (idempotent)."""
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_topics (url_hash, title_normalized, first_seen_at) "
            "VALUES (?, ?, ?)",
            (url_hash, title_normalized, first_seen_at),
        )

    def seen_topics_in_window(self, days: int) -> list[sqlite3.Row]:
        """Return seen_topics rows first_seen_at within the last N days."""
        return self.conn.execute(
            "SELECT * FROM seen_topics WHERE first_seen_at >= datetime('now', ?)",
            (f"-{int(days)} days",),
        ).fetchall()

    def mark_topic_scripted(self, topic_id: int) -> None:
        self.conn.execute("UPDATE topics SET status='scripted' WHERE id=?", (topic_id,))

    def mark_topic_expired(self, topic_id: int) -> None:
        self.conn.execute("UPDATE topics SET status='expired' WHERE id=?", (topic_id,))

    def mark_topic_rejected_off_niche(self, topic_id: int) -> None:
        """Terminal status for legacy topics failing the on-niche gate (Issue 39)."""
        self.conn.execute(
            "UPDATE topics SET status='rejected_off_niche' WHERE id=? AND status='unscripted'",
            (topic_id,),
        )

    # ---- Pivot.6: scripts ----

    def insert_script(
        self,
        *,
        script_id: str,
        topic_id: int,
        title: str,
        narration: str,
        shots_json: str,
        style_suffix: str,
        ollama_model: str,
        created_at: str,
        topic_score_json: str | None = None,
        category: str | None = None,
        status: str = "pending",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO scripts (
                script_id, topic_id, title, narration, shots_json,
                style_suffix, ollama_model, created_at,
                topic_score_json, category, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (script_id, topic_id, title, narration, shots_json,
             style_suffix, ollama_model, created_at,
             topic_score_json, category, status),
        )

    def scripts_awaiting_narration(self) -> list[sqlite3.Row]:
        """Directed scripts waiting for qwen narration-only completion."""
        return self.conn.execute(
            "SELECT * FROM scripts WHERE status='directed' ORDER BY created_at ASC"
        ).fetchall()

    def set_script_narration_pending(
        self,
        script_id: str,
        narration: str,
    ) -> None:
        self.conn.execute(
            "UPDATE scripts SET narration=?, status='pending' WHERE script_id=?",
            (narration, script_id),
        )

    def clips_at_publish_at(
        self,
        publish_at_utc: str,
        *,
        exclude_clip_id: str | None = None,
    ) -> list[sqlite3.Row]:
        """Non-published clips already holding a publish_at_utc slot."""
        sql = (
            "SELECT clip_id FROM clips "
            "WHERE publish_at_utc=? AND youtube_video_id IS NULL"
        )
        params: list = [publish_at_utc]
        if exclude_clip_id:
            sql += " AND clip_id != ?"
            params.append(exclude_clip_id)
        return self.conn.execute(sql, params).fetchall()

    def get_script(self, script_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM scripts WHERE script_id=?", (script_id,)
        ).fetchone()

    def pending_scripts(self, limit: int = 2) -> list[sqlite3.Row]:
        """Return highest-scoring pending scripts not yet rendered."""
        return self.conn.execute(
            "SELECT * FROM scripts WHERE status='pending' "
            "ORDER BY quality_score DESC NULLS LAST LIMIT ?",
            (limit,),
        ).fetchall()

    def update_script_status(
        self,
        script_id: str,
        status: str,
        *,
        rejection_reason: str | None = None,
        quality_score: float | None = None,
        quality_score_json: str | None = None,
    ) -> None:
        sets = ["status=?"]
        params: list = [status]
        if rejection_reason is not None:
            sets.append("rejection_reason=?")
            params.append(rejection_reason)
        if quality_score is not None:
            sets.append("quality_score=?")
            params.append(quality_score)
        if quality_score_json is not None:
            sets.append("quality_score_json=?")
            params.append(quality_score_json)
        params.append(script_id)
        self.conn.execute(
            f"UPDATE scripts SET {', '.join(sets)} WHERE script_id=?", params
        )

    # ---- Pivot.6: generation_jobs ----

    def upsert_generation_job(
        self,
        *,
        job_id: str,
        script_id: str,
        shot_index: int,
        provider: str,
        prompt: str,
        duration_s: int,
        status: str,
        external_id: str | None = None,
        output_path: str | None = None,
        cost_cents: int | None = None,
        submitted_at: str | None = None,
        completed_at: str | None = None,
        error: str | None = None,
    ) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.conn.execute(
            """
            INSERT INTO generation_jobs (
                job_id, script_id, shot_index, provider, prompt, duration_s,
                status, external_id, output_path, cost_cents,
                submitted_at, completed_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status=excluded.status,
                external_id=excluded.external_id,
                output_path=excluded.output_path,
                cost_cents=excluded.cost_cents,
                completed_at=excluded.completed_at,
                error=excluded.error
            """,
            (
                job_id, script_id, shot_index, provider, prompt, duration_s,
                status, external_id, output_path, cost_cents,
                submitted_at or now, completed_at or now, error,
            ),
        )

    def succeeded_generation_jobs(self, script_id: str) -> list[sqlite3.Row]:
        """Return succeeded generation_jobs for a script, ordered by shot_index."""
        return self.conn.execute(
            "SELECT * FROM generation_jobs "
            "WHERE script_id=? AND status='succeeded' "
            "ORDER BY shot_index ASC",
            (script_id,),
        ).fetchall()

    # ---- Pivot.6: clips for generation run ----

    def clips_for_generation_run(self) -> list[sqlite3.Row]:
        """Clips queued for AI video generation: ai_generated kind with a script_id."""
        return self.conn.execute(
            "SELECT * FROM clips WHERE content_kind='ai_generated' AND script_id IS NOT NULL "
            "ORDER BY created_at ASC, clip_id ASC"
        ).fetchall()

    def get_clip_with_script(self, clip_id: str) -> sqlite3.Row | None:
        """Joined clips + scripts row for the AI generation pipeline.

        Scripts columns are prefixed with `s_` to avoid collision with clips
        columns that share names (title, status, created_at).
        Returns None if the clip doesn't exist or has no linked script.
        """
        return self.conn.execute(
            """
            SELECT
                c.*,
                s.script_id    AS s_script_id,
                s.title        AS s_title,
                s.narration    AS s_narration,
                s.shots_json   AS s_shots_json,
                s.style_suffix AS s_style_suffix,
                s.category     AS s_category,
                s.status       AS s_status
            FROM clips c
            JOIN scripts s ON s.script_id = c.script_id
            WHERE c.clip_id = ?
            """,
            (clip_id,),
        ).fetchone()

    # ---- retention delete helpers ----

    def delete_dup_hashes_before(self, cutoff_iso: str) -> int:
        """Delete dup_hashes rows created before cutoff_iso. Returns deleted count."""
        cur = self.conn.execute(
            "DELETE FROM dup_hashes WHERE created_at <= ?", (cutoff_iso,)
        )
        return cur.rowcount

    def delete_quota_usage_before(self, cutoff_date: str) -> int:
        """Delete quota_usage rows with date <= cutoff_date (YYYY-MM-DD). Returns deleted count."""
        cur = self.conn.execute(
            "DELETE FROM quota_usage WHERE date <= ?", (cutoff_date,)
        )
        return cur.rowcount
