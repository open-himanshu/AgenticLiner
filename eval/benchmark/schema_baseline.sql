-- AgenticLiner Benchmark Setup B: Plain SQL Ordinary Constraints Baseline
-- Contains only standard SQLite table definitions, FOREIGN KEYs, UNIQUE constraints,
-- CHECK constraints, and SQL BEFORE INSERT/UPDATE triggers (plain SQL only).

-- Rule: Enable SQLite foreign-key constraint enforcement on every connection.
PRAGMA foreign_keys = ON;

-- 0. Users & Authentication
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    -- Rule: Enforce valid campus RBAC persona roles at the schema level.
    role TEXT NOT NULL CHECK (role IN ('supervisor', 'organiser', 'data_manager', 'participant')),
    full_name TEXT NOT NULL,
    department TEXT DEFAULT 'General',
    phone TEXT,
    bio TEXT,
    avatar_url TEXT,
    preferred_language TEXT DEFAULT 'en',
    notifications_enabled BOOLEAN DEFAULT 1,
    is_verified BOOLEAN DEFAULT 1,
    failed_attempts INTEGER DEFAULT 0,
    locked_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 0.1 OTP Verifications Table
CREATE TABLE IF NOT EXISTS otp_verifications (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    otp_code TEXT NOT NULL,
    purpose TEXT NOT NULL,
    payload_json TEXT,
    attempts INTEGER DEFAULT 0,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 1. Events Table
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    brief TEXT NOT NULL,
    event_type TEXT DEFAULT 'general',
    -- Rule: Expected participant count cannot be negative.
    expected_participants INTEGER DEFAULT 100 CHECK (expected_participants >= 0),
    -- Rule: Event budget cannot be negative.
    budget REAL NOT NULL DEFAULT 0 CHECK (budget >= 0),
    organizer_department TEXT DEFAULT 'School of AI',
    approval_status TEXT DEFAULT 'auto_approved',
    status TEXT DEFAULT 'planned',
    image_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Rooms / Venues (Campus Infrastructure)
CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    -- Rule: Campus rooms must declare a positive seating capacity.
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    location TEXT,
    has_projector BOOLEAN DEFAULT 1,
    has_audio BOOLEAN DEFAULT 1,
    requires_special_approval BOOLEAN DEFAULT 0,
    image_url TEXT
);

-- 3. Speakers & Faculty Mentors
CREATE TABLE IF NOT EXISTS speakers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT,
    topics TEXT,
    email TEXT,
    phone TEXT,
    availability_json TEXT,
    image_url TEXT
);

-- 4. Resources & Equipment Catalog (Campus Logistics Inventory)
CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    -- Rule: Equipment stock cannot drop below zero (CHECK(stock >= 0)).
    stock INTEGER NOT NULL DEFAULT 1 CHECK (stock >= 0),
    -- Rule: Allocated stock counter cannot be negative.
    allocated_stock INTEGER NOT NULL DEFAULT 0 CHECK (allocated_stock >= 0),
    unit TEXT DEFAULT 'unit',
    requires_approval BOOLEAN DEFAULT 0,
    description TEXT,
    image_url TEXT
);

-- 5. Sessions / Agenda Breakdown
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    speaker_id TEXT,
    room_id TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_minutes INTEGER DEFAULT 60,
    -- Rule: Expected attendance for a session cannot be negative.
    expected_attendance INTEGER DEFAULT 50 CHECK (expected_attendance >= 0),
    depends_on TEXT,
    track TEXT DEFAULT 'General',
    -- Rule: CHECK(end > start) enforces strictly positive session time windows when timestamps exist.
    CHECK (start_time IS NULL OR end_time IS NULL OR end_time > start_time),
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY(room_id) REFERENCES rooms(id),
    FOREIGN KEY(speaker_id) REFERENCES speakers(id)
);

-- 6. Resource Allocations / Bookings
CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    resource_id TEXT,
    room_id TEXT,
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    -- Rule: Booking quantity must be non-negative.
    quantity INTEGER DEFAULT 1 CHECK (quantity >= 0),
    estimated_cost REAL NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
    approval_status TEXT DEFAULT 'auto_approved',
    status TEXT DEFAULT 'confirmed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Rule: CHECK(end > start) rejects bookings whose end_time is not strictly after start_time.
    CHECK (start_time IS NULL OR end_time IS NULL OR end_time > start_time),
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY(room_id) REFERENCES rooms(id),
    FOREIGN KEY(resource_id) REFERENCES resources(id)
);

-- 7. Students / Attendees
CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    department TEXT NOT NULL,
    year INTEGER NOT NULL,
    interests TEXT
);

-- 8. Event Registrations & Attendee Management
CREATE TABLE IF NOT EXISTS registrations (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'confirmed',
    interests_snapshot TEXT,
    preferred_sessions TEXT,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY(student_id) REFERENCES students(id),
    -- Rule: Prevent duplicate student registration for the same event.
    UNIQUE(event_id, student_id)
);

-- 9. Session Attendance
CREATE TABLE IF NOT EXISTS attendance (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    checked_in_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    check_in_code TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(student_id) REFERENCES students(id),
    -- Rule: Prevent duplicate check-in for the same student and session.
    UNIQUE(session_id, student_id)
);

-- 10. Feedback
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    student_id TEXT,
    -- Rule: Restrict feedback ratings to the 1..5 scale.
    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
    comment TEXT,
    sentiment TEXT,
    sentiment_score REAL,
    theme TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);

-- 11. Outbox
CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    type TEXT DEFAULT 'general',
    status TEXT DEFAULT 'held',
    operation_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);

-- 12. Verifiable Certificates
CREATE TABLE IF NOT EXISTS certificates (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    qr_code_path TEXT,
    pdf_path TEXT,
    verified_count INTEGER DEFAULT 0,
    FOREIGN KEY(student_id) REFERENCES students(id),
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);

-- 13. Audit Log
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    event_id TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT,
    result TEXT
);

-- 14. Requests that exhausted automatic safety retries
CREATE TABLE IF NOT EXISTS human_review_queue (
    id TEXT PRIMARY KEY,
    event_id TEXT,
    actor TEXT NOT NULL,
    operation_name TEXT NOT NULL,
    request_json TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    last_error TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 15. Historical Events for ML Baseline / Training
CREATE TABLE IF NOT EXISTS historical_events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    event_type TEXT NOT NULL,
    headcount INTEGER NOT NULL,
    duration_hours REAL NOT NULL,
    rooms_needed INTEGER NOT NULL,
    volunteers_needed INTEGER NOT NULL,
    mics_needed INTEGER NOT NULL,
    food_packs_needed INTEGER NOT NULL,
    buses_needed INTEGER DEFAULT 0
);

-- 16. Agent Memories
CREATE TABLE IF NOT EXISTS agent_memories (
    id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    department TEXT DEFAULT 'Campus',
    favourite_venues TEXT DEFAULT '[]',
    favourite_equipment TEXT DEFAULT '[]',
    typical_headcount INTEGER DEFAULT 100,
    preferred_start_time TEXT DEFAULT '10:00:00',
    preferred_end_time TEXT DEFAULT '13:00:00',
    preferred_days TEXT DEFAULT '["Friday"]',
    memory_notes TEXT DEFAULT '[]',
    total_events_planned INTEGER DEFAULT 0,
    last_event_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_memories_user_id ON agent_memories(user_id);

-- =============================================================================
-- Ordinary SQL Triggers (Plain SQL Baseline Rules for Setup B)
-- =============================================================================

-- Rule: Reject inserting a confirmed room booking that overlaps an existing confirmed booking in the same room.
CREATE TRIGGER IF NOT EXISTS trg_baseline_no_room_overlap_insert
BEFORE INSERT ON bookings
FOR EACH ROW
WHEN NEW.room_id IS NOT NULL
 AND COALESCE(NEW.status, 'confirmed') = 'confirmed'
 AND NEW.start_time IS NOT NULL
 AND NEW.end_time IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: overlapping confirmed booking for the same room')
    WHERE EXISTS (
        SELECT 1
        FROM bookings AS existing
        WHERE existing.room_id = NEW.room_id
          AND existing.status = 'confirmed'
          AND existing.start_time IS NOT NULL
          AND existing.end_time IS NOT NULL
          AND existing.start_time < NEW.end_time
          AND existing.end_time > NEW.start_time
    );
END;

-- Rule: Reject updating a confirmed room booking so that it overlaps another confirmed booking in the same room.
CREATE TRIGGER IF NOT EXISTS trg_baseline_no_room_overlap_update
BEFORE UPDATE ON bookings
FOR EACH ROW
WHEN NEW.room_id IS NOT NULL
 AND COALESCE(NEW.status, 'confirmed') = 'confirmed'
 AND NEW.start_time IS NOT NULL
 AND NEW.end_time IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: overlapping confirmed booking for the same room')
    WHERE EXISTS (
        SELECT 1
        FROM bookings AS existing
        WHERE existing.id != NEW.id
          AND existing.room_id = NEW.room_id
          AND existing.status = 'confirmed'
          AND existing.start_time IS NOT NULL
          AND existing.end_time IS NOT NULL
          AND existing.start_time < NEW.end_time
          AND existing.end_time > NEW.start_time
    );
END;

-- Rule: Reject inserting a confirmed room booking when event expected_participants exceeds room capacity (unless breakout sessions define per-room attendance).
CREATE TRIGGER IF NOT EXISTS trg_baseline_room_capacity_insert
BEFORE INSERT ON bookings
FOR EACH ROW
WHEN NEW.room_id IS NOT NULL
 AND COALESCE(NEW.status, 'confirmed') = 'confirmed'
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: event headcount exceeds room capacity')
    WHERE NOT EXISTS (
        SELECT 1 FROM sessions AS s
        WHERE s.event_id = NEW.event_id
    )
    AND EXISTS (
        SELECT 1
        FROM events AS e
        JOIN rooms AS r ON r.id = NEW.room_id
        WHERE e.id = NEW.event_id
          AND e.expected_participants > r.capacity
    );
END;

-- Rule: Reject updating a confirmed room booking if event expected_participants exceeds the target room capacity (when no breakout sessions exist).
CREATE TRIGGER IF NOT EXISTS trg_baseline_room_capacity_update
BEFORE UPDATE ON bookings
FOR EACH ROW
WHEN NEW.room_id IS NOT NULL
 AND COALESCE(NEW.status, 'confirmed') = 'confirmed'
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: event headcount exceeds room capacity')
    WHERE NOT EXISTS (
        SELECT 1 FROM sessions AS s
        WHERE s.event_id = NEW.event_id
    )
    AND EXISTS (
        SELECT 1
        FROM events AS e
        JOIN rooms AS r ON r.id = NEW.room_id
        WHERE e.id = NEW.event_id
          AND e.expected_participants > r.capacity
    );
END;

-- Rule: Reject raising an event's expected_participants above the capacity of any already-confirmed room booking without breakout sessions.
CREATE TRIGGER IF NOT EXISTS trg_baseline_event_capacity_update
BEFORE UPDATE OF expected_participants ON events
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: updated event headcount exceeds booked room capacity')
    WHERE NOT EXISTS (
        SELECT 1 FROM sessions AS s
        WHERE s.event_id = NEW.id
    )
    AND EXISTS (
        SELECT 1
        FROM bookings AS b
        JOIN rooms AS r ON r.id = b.room_id
        WHERE b.event_id = NEW.id
          AND b.room_id IS NOT NULL
          AND b.status = 'confirmed'
          AND NEW.expected_participants > r.capacity
    );
END;

-- Rule: Reject inserting a session whose expected_attendance exceeds the assigned room capacity.
CREATE TRIGGER IF NOT EXISTS trg_baseline_session_capacity_insert
BEFORE INSERT ON sessions
FOR EACH ROW
WHEN NEW.room_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: session expected_attendance exceeds room capacity')
    WHERE EXISTS (
        SELECT 1
        FROM rooms AS r
        WHERE r.id = NEW.room_id
          AND NEW.expected_attendance > r.capacity
    );
END;

-- Rule: Reject updating a session so its expected_attendance exceeds the assigned room capacity.
CREATE TRIGGER IF NOT EXISTS trg_baseline_session_capacity_update
BEFORE UPDATE ON sessions
FOR EACH ROW
WHEN NEW.room_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: session expected_attendance exceeds room capacity')
    WHERE EXISTS (
        SELECT 1
        FROM rooms AS r
        WHERE r.id = NEW.room_id
          AND NEW.expected_attendance > r.capacity
    );
END;

-- Rule: Reject inserting a confirmed resource booking whose concurrent quantity exceeds available resource stock.
CREATE TRIGGER IF NOT EXISTS trg_baseline_resource_stock_insert
BEFORE INSERT ON bookings
FOR EACH ROW
WHEN NEW.resource_id IS NOT NULL
 AND COALESCE(NEW.status, 'confirmed') = 'confirmed'
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: resource booking quantity exceeds available stock')
    WHERE EXISTS (
        SELECT 1
        FROM resources AS r
        WHERE r.id = NEW.resource_id
          AND (
              (
                  (NEW.start_time IS NULL OR NEW.end_time IS NULL)
                  AND COALESCE(NEW.quantity, 1) + (
                      SELECT COALESCE(SUM(COALESCE(e.quantity, 1)), 0)
                      FROM bookings AS e
                      WHERE e.resource_id = NEW.resource_id
                        AND e.status = 'confirmed'
                  ) > r.stock
              )
              OR (
                  NEW.start_time IS NOT NULL
                  AND NEW.end_time IS NOT NULL
                  AND (
                      COALESCE(NEW.quantity, 1) + (
                          SELECT COALESCE(SUM(COALESCE(e.quantity, 1)), 0)
                          FROM bookings AS e
                          WHERE e.resource_id = NEW.resource_id
                            AND e.status = 'confirmed'
                            AND (
                                e.start_time IS NULL
                                OR e.end_time IS NULL
                                OR (e.start_time <= NEW.start_time AND e.end_time > NEW.start_time)
                            )
                      ) > r.stock
                      OR EXISTS (
                          SELECT 1
                          FROM bookings AS anchor
                          WHERE anchor.resource_id = NEW.resource_id
                            AND anchor.status = 'confirmed'
                            AND anchor.start_time IS NOT NULL
                            AND anchor.start_time >= NEW.start_time
                            AND anchor.start_time < NEW.end_time
                            AND COALESCE(NEW.quantity, 1) + (
                                SELECT COALESCE(SUM(COALESCE(e.quantity, 1)), 0)
                                FROM bookings AS e
                                WHERE e.resource_id = NEW.resource_id
                                  AND e.status = 'confirmed'
                                  AND (
                                      e.start_time IS NULL
                                      OR e.end_time IS NULL
                                      OR (e.start_time <= anchor.start_time AND e.end_time > anchor.start_time)
                                  )
                            ) > r.stock
                      )
                  )
              )
          )
    );
END;

-- Rule: Reject updating a confirmed resource booking when concurrent resource demand exceeds available stock.
CREATE TRIGGER IF NOT EXISTS trg_baseline_resource_stock_update
BEFORE UPDATE ON bookings
FOR EACH ROW
WHEN NEW.resource_id IS NOT NULL
 AND COALESCE(NEW.status, 'confirmed') = 'confirmed'
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: resource booking quantity exceeds available stock')
    WHERE EXISTS (
        SELECT 1
        FROM resources AS r
        WHERE r.id = NEW.resource_id
          AND (
              (
                  (NEW.start_time IS NULL OR NEW.end_time IS NULL)
                  AND COALESCE(NEW.quantity, 1) + (
                      SELECT COALESCE(SUM(COALESCE(e.quantity, 1)), 0)
                      FROM bookings AS e
                      WHERE e.id != NEW.id
                        AND e.resource_id = NEW.resource_id
                        AND e.status = 'confirmed'
                  ) > r.stock
              )
              OR (
                  NEW.start_time IS NOT NULL
                  AND NEW.end_time IS NOT NULL
                  AND (
                      COALESCE(NEW.quantity, 1) + (
                          SELECT COALESCE(SUM(COALESCE(e.quantity, 1)), 0)
                          FROM bookings AS e
                          WHERE e.id != NEW.id
                            AND e.resource_id = NEW.resource_id
                            AND e.status = 'confirmed'
                            AND (
                                e.start_time IS NULL
                                OR e.end_time IS NULL
                                OR (e.start_time <= NEW.start_time AND e.end_time > NEW.start_time)
                            )
                      ) > r.stock
                      OR EXISTS (
                          SELECT 1
                          FROM bookings AS anchor
                          WHERE anchor.id != NEW.id
                            AND anchor.resource_id = NEW.resource_id
                            AND anchor.status = 'confirmed'
                            AND anchor.start_time IS NOT NULL
                            AND anchor.start_time >= NEW.start_time
                            AND anchor.start_time < NEW.end_time
                            AND COALESCE(NEW.quantity, 1) + (
                                SELECT COALESCE(SUM(COALESCE(e.quantity, 1)), 0)
                                FROM bookings AS e
                                WHERE e.id != NEW.id
                                  AND e.resource_id = NEW.resource_id
                                  AND e.status = 'confirmed'
                                  AND (
                                      e.start_time IS NULL
                                      OR e.end_time IS NULL
                                      OR (e.start_time <= anchor.start_time AND e.end_time > anchor.start_time)
                                  )
                            ) > r.stock
                      )
                  )
              )
          )
    );
END;

-- Rule: Reject inserting a session whose speaker is already assigned to an overlapping session.
CREATE TRIGGER IF NOT EXISTS trg_baseline_speaker_overlap_insert
BEFORE INSERT ON sessions
FOR EACH ROW
WHEN NEW.speaker_id IS NOT NULL
 AND NEW.start_time IS NOT NULL
 AND NEW.end_time IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: speaker is already scheduled in an overlapping session')
    WHERE EXISTS (
        SELECT 1
        FROM sessions AS existing
        WHERE existing.speaker_id = NEW.speaker_id
          AND existing.start_time IS NOT NULL
          AND existing.end_time IS NOT NULL
          AND existing.start_time < NEW.end_time
          AND existing.end_time > NEW.start_time
    );
END;

-- Rule: Reject updating a session when the speaker is already assigned to another overlapping session.
CREATE TRIGGER IF NOT EXISTS trg_baseline_speaker_overlap_update
BEFORE UPDATE ON sessions
FOR EACH ROW
WHEN NEW.speaker_id IS NOT NULL
 AND NEW.start_time IS NOT NULL
 AND NEW.end_time IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Baseline SQL constraint: speaker is already scheduled in an overlapping session')
    WHERE EXISTS (
        SELECT 1
        FROM sessions AS existing
        WHERE existing.id != NEW.id
          AND existing.speaker_id = NEW.speaker_id
          AND existing.start_time IS NOT NULL
          AND existing.end_time IS NOT NULL
          AND existing.start_time < NEW.end_time
          AND existing.end_time > NEW.start_time
    );
END;
