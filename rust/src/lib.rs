use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use rusqlite::{Connection, OpenFlags};

type MsgRow = (Option<String>, bool, String, i64, Option<String>, bool);

fn open_ro(db_path: &str) -> PyResult<Connection> {
    Connection::open_with_flags(
        db_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI,
    )
    .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

/// Heuristic typedstream text extraction. Mirrors the reference Python exactly.
#[pyfunction]
fn decode_attributed_body(blob: &[u8]) -> Option<String> {
    let needle = b"NSString";
    let pos = blob
        .windows(needle.len())
        .position(|w| w == needle)?;
    // slice AFTER the NSString occurrence, then skip 5 bytes
    let rest = &blob[pos + needle.len()..];
    let rest = rest.get(5..)?;
    let (len, payload) = match rest.first()? {
        0x81 => {
            let lo = *rest.get(1)? as usize;
            let hi = *rest.get(2)? as usize;
            (lo | (hi << 8), rest.get(3..)?)
        }
        &b => (b as usize, rest.get(1..)?),
    };
    if len == 0 {
        return None;
    }
    let end = len.min(payload.len());
    Some(String::from_utf8_lossy(&payload[..end]).into_owned())
}

fn map_msg_row(row: &rusqlite::Row) -> rusqlite::Result<MsgRow> {
    let text: Option<String> = row.get(0)?;
    let body: Option<Vec<u8>> = row.get(1)?;
    let is_from_me: i64 = row.get(2)?;
    let handle: Option<String> = row.get(3)?;
    let date_raw: i64 = row.get(4)?;
    let service: Option<String> = row.get(5)?;
    let has_attachment: i64 = row.get(6)?;

    let is_from_me = is_from_me != 0;
    let resolved_text = match text {
        Some(t) if !t.is_empty() => Some(t),
        _ => body.as_deref().and_then(decode_attributed_body),
    };
    let sender = if is_from_me {
        "me".to_string()
    } else {
        handle.unwrap_or_else(|| "unknown".to_string())
    };
    Ok((
        resolved_text,
        is_from_me,
        sender,
        date_raw,
        service,
        has_attachment != 0,
    ))
}

const MSG_SELECT: &str = "SELECT m.text, m.attributedBody, m.is_from_me, h.id, m.date, m.service, m.cache_has_attachments \
     FROM message m LEFT JOIN handle h ON h.ROWID = m.handle_id";

#[pyfunction]
#[pyo3(signature = (db_path, contact=None, chat_id=None, limit=100))]
fn read_messages(
    db_path: String,
    contact: Option<String>,
    chat_id: Option<i64>,
    limit: i64,
) -> PyResult<Vec<MsgRow>> {
    let conn = open_ro(&db_path)?;

    let mut clauses: Vec<&str> = Vec::new();
    let mut params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();
    if let Some(cid) = chat_id {
        clauses.push("m.ROWID IN (SELECT message_id FROM chat_message_join WHERE chat_id = ?)");
        params.push(Box::new(cid));
    }
    if let Some(c) = contact {
        clauses.push("h.id = ?");
        params.push(Box::new(c));
    }
    let mut sql = MSG_SELECT.to_string();
    if !clauses.is_empty() {
        sql.push_str(" WHERE ");
        sql.push_str(&clauses.join(" AND "));
    }
    sql.push_str(" ORDER BY m.date DESC LIMIT ?");
    params.push(Box::new(limit));

    let param_refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let mut stmt = conn.prepare(&sql).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let rows = stmt
        .query_map(param_refs.as_slice(), map_msg_row)
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

#[pyfunction]
#[pyo3(signature = (db_path, query, limit=100))]
fn search_messages(db_path: String, query: String, limit: i64) -> PyResult<Vec<MsgRow>> {
    let conn = open_ro(&db_path)?;
    let sql = format!("{MSG_SELECT} WHERE m.text LIKE ? ORDER BY m.date DESC LIMIT ?");
    let mut stmt = conn.prepare(&sql).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let rows = stmt
        .query_map(rusqlite::params![format!("%{query}%"), limit], map_msg_row)
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

#[pyfunction]
#[pyo3(signature = (db_path, limit=100))]
fn list_chats(
    db_path: String,
    limit: i64,
) -> PyResult<Vec<(i64, String, Option<String>, Option<String>)>> {
    let conn = open_ro(&db_path)?;
    let sql = "SELECT c.ROWID, c.chat_identifier, c.display_name, c.service_name, MAX(m.date) AS last \
         FROM chat c JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID \
         JOIN message m ON m.ROWID = cmj.message_id \
         GROUP BY c.ROWID ORDER BY last DESC LIMIT ?";
    let mut stmt = conn.prepare(sql).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let rows = stmt
        .query_map([limit], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
            ))
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

#[pyfunction]
#[pyo3(signature = (db_path, limit=100, query=None))]
fn list_contacts(
    db_path: String,
    limit: i64,
    query: Option<String>,
) -> PyResult<Vec<(String, Option<String>)>> {
    let conn = open_ro(&db_path)?;
    let needle = query
        .as_ref()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    if let Some(q) = needle {
        let pattern = format!("%{q}%");
        let mut stmt = conn
            .prepare(
                "SELECT DISTINCT id, service FROM handle \
                 WHERE id LIKE ?1 COLLATE NOCASE ORDER BY id LIMIT ?2",
            )
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        let rows = stmt
            .query_map(rusqlite::params![pattern, limit], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?))
            })
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        return rows
            .collect::<rusqlite::Result<Vec<_>>>()
            .map_err(|e| PyRuntimeError::new_err(e.to_string()));
    }
    let mut stmt = conn
        .prepare("SELECT DISTINCT id, service FROM handle ORDER BY id LIMIT ?")
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let rows = stmt
        .query_map([limit], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?))
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

/// Owned row data with no Python objects, so it can cross the GIL boundary
/// into a rayon parallel section.
struct RawMsg {
    text: Option<String>,
    body: Option<Vec<u8>>,
    is_from_me: bool,
    handle: Option<String>,
    date: i64,
    service: Option<String>,
    has_attach: bool,
}

/// Full-history search that ALSO matches messages whose text is stored in an
/// attributedBody blob (which `text LIKE` misses entirely). Decodes and matches
/// every message in parallel across all cores with the GIL released — the work
/// a Python-only server must do single-threaded in a Python loop.
#[pyfunction]
#[pyo3(signature = (db_path, query, limit=100))]
fn search_all(py: Python<'_>, db_path: String, query: String, limit: i64) -> PyResult<Vec<MsgRow>> {
    let conn = open_ro(&db_path)?;
    let sql = format!("{MSG_SELECT} ORDER BY m.date DESC");
    let mut stmt = conn.prepare(&sql).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let raws: Vec<RawMsg> = stmt
        .query_map([], |row| {
            Ok(RawMsg {
                text: row.get(0)?,
                body: row.get(1)?,
                is_from_me: row.get::<_, i64>(2)? != 0,
                handle: row.get(3)?,
                date: row.get(4)?,
                service: row.get(5)?,
                has_attach: row.get::<_, i64>(6)? != 0,
            })
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?
        .collect::<rusqlite::Result<Vec<_>>>()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

    let needle = query.to_lowercase();
    let matched: Vec<MsgRow> = py.allow_threads(|| {
        use rayon::prelude::*;
        raws.par_iter()
            .filter_map(|r| {
                let text = match &r.text {
                    Some(t) if !t.is_empty() => t.clone(),
                    _ => r.body.as_deref().and_then(decode_attributed_body)?,
                };
                if !text.to_lowercase().contains(&needle) {
                    return None;
                }
                let sender = if r.is_from_me {
                    "me".to_string()
                } else {
                    r.handle.clone().unwrap_or_else(|| "unknown".to_string())
                };
                Some((Some(text), r.is_from_me, sender, r.date, r.service.clone(), r.has_attach))
            })
            .collect()
    });
    Ok(matched.into_iter().take(limit.max(0) as usize).collect())
}

/// Batched parallel decode: one FFI crossing, all cores, GIL released.
#[pyfunction]
fn decode_many(py: Python<'_>, blobs: Vec<Vec<u8>>) -> Vec<Option<String>> {
    py.allow_threads(|| {
        use rayon::prelude::*;
        blobs.par_iter().map(|b| decode_attributed_body(b)).collect()
    })
}

#[pymodule]
fn imsgcore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(read_messages, m)?)?;
    m.add_function(wrap_pyfunction!(search_messages, m)?)?;
    m.add_function(wrap_pyfunction!(search_all, m)?)?;
    m.add_function(wrap_pyfunction!(list_chats, m)?)?;
    m.add_function(wrap_pyfunction!(list_contacts, m)?)?;
    m.add_function(wrap_pyfunction!(decode_attributed_body, m)?)?;
    m.add_function(wrap_pyfunction!(decode_many, m)?)?;
    Ok(())
}
