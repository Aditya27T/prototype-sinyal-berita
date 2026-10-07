import { useEffect, useMemo, useRef, useState } from "react";

const API = "/api";

const VIEWS = [
  { key: "relevant", label: "Relevan" },
  { key: "noise", label: "Tidak relevan" },
  { key: "pending", label: "Menunggu AI" },
  { key: "all", label: "Semua" },
];

const PAGES = [
  { key: "posts", label: "Posting" },
  { key: "events", label: "Event" },
  { key: "reports", label: "Laporan" },
];

function statusOf(post) {
  if (post.is_relevant === true) return "relevant";
  if (post.is_relevant === false) return "noise";
  return "pending";
}

function formatTime(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// Hitung kemunculan sebuah field, urut dari yang terbanyak.
function tally(posts, field) {
  const counts = new Map();
  for (const p of posts) {
    if (p[field]) counts.set(p[field], (counts.get(p[field]) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

export default function App() {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState("relevant");
  const [search, setSearch] = useState("");
  const [location, setLocation] = useState(null);
  const [issue, setIssue] = useState(null);
  const [platform, setPlatform] = useState(null); // null = semua; "instagram" | "threads"
  const [page, setPage] = useState("posts");
  const autoSwitched = useRef(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/posts/all?limit=200`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      setPosts(await res.json());
    } catch (e) {
      setError(`Gagal memuat data (${e.message}). Pastikan FastAPI jalan di :8000.`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(() => {
    const s = { total: posts.length, relevant: 0, noise: 0, pending: 0 };
    for (const p of posts) s[statusOf(p)] += 1;
    return s;
  }, [posts]);

  const relevantPosts = useMemo(() => posts.filter((p) => statusOf(p) === "relevant"), [posts]);
  const analyzedPosts = useMemo(() => posts.filter((p) => statusOf(p) !== "pending"), [posts]);
  const locations = useMemo(() => tally(analyzedPosts, "location"), [analyzedPosts]);
  const issues = useMemo(() => tally(analyzedPosts, "issue_hint"), [analyzedPosts]);

  // Jangan daratkan user di tab kosong: kalau tidak ada yang relevan,
  // tampilkan Semua agar halaman pertama langsung berisi.
  useEffect(() => {
    if (!loading && !autoSwitched.current && posts.length > 0) {
      autoSwitched.current = true;
      if (relevantPosts.length === 0) setView("all");
    }
  }, [loading, posts, relevantPosts.length]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const ts = (p) => new Date(p.published_at ?? p.collected_at ?? 0).getTime() || 0;
    return posts
      .filter((p) => view === "all" || statusOf(p) === view)
      .filter((p) => !platform || p.platform === platform)
      .filter((p) => !location || p.location === location)
      .filter((p) => !issue || p.issue_hint === issue)
      .filter((p) => !q || `${p.text} ${p.author ?? ""}`.toLowerCase().includes(q))
      .sort((a, b) => ts(b) - ts(a) || (b.relevance_score ?? -1) - (a.relevance_score ?? -1));
  }, [posts, view, search, location, issue, platform]);

  // jumlah per platform mengikuti tab aktif (Relevan/Noise/...), bukan seluruh data
  const platformCounts = useMemo(() => {
    const c = {};
    for (const p of posts) {
      if (view !== "all" && statusOf(p) !== view) continue;
      c[p.platform] = (c[p.platform] ?? 0) + 1;
    }
    return c;
  }, [posts, view]);
  const platforms = Object.keys(platformCounts).sort();

  const analyzed = stats.relevant + stats.noise;
  const hasFilter = search || location || issue || platform;

  function clearFilters() {
    setSearch("");
    setLocation(null);
    setIssue(null);
    setPlatform(null);
  }

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <h1>Telinga Digital</h1>
          <p>Social listening Malang Raya · review prototype</p>
        </div>
        <button className="btn" onClick={load} disabled={loading}>
          {loading ? "Memuat…" : "Muat ulang"}
        </button>
      </header>

      <nav className="pages" role="tablist" aria-label="Halaman">
        {PAGES.map((p) => (
          <button
            key={p.key}
            role="tab"
            aria-selected={page === p.key}
            className={page === p.key ? "active" : ""}
            onClick={() => setPage(p.key)}
          >
            {p.label}
          </button>
        ))}
      </nav>

      {page === "events" && <EventsPage />}
      {page === "reports" && <ReportsPage />}
      {page === "posts" && (
        <>
      <section className="funnel" aria-label="Ringkasan pipeline">
        <Stat label="Terkumpul" value={stats.total} hint="posting masuk pipeline" />
        <Stat label="Dianalisis AI" value={analyzed} hint={`${stats.pending} menunggu`} />
        <Stat
          label="Relevan"
          value={stats.relevant}
          hint={analyzed ? `${Math.round((stats.relevant / analyzed) * 100)}% dari yang dianalisis` : "—"}
          tone="good"
        />
        <Stat label="Tidak relevan" value={stats.noise} hint="iklan, promosi, di luar isu publik" />
      </section>

      {error && <div className="alert">{error}</div>}

      <div className="layout">
        <main>
          <div className="toolbar">
            <div className="segmented" role="tablist">
              {VIEWS.map((v) => (
                <button
                  key={v.key}
                  role="tab"
                  aria-selected={view === v.key}
                  className={view === v.key ? "active" : ""}
                  onClick={() => setView(v.key)}
                >
                  {v.label}
                  <span className="count">{v.key === "all" ? stats.total : stats[v.key]}</span>
                </button>
              ))}
            </div>
            {platforms.length > 1 && (
              <div className="segmented" role="tablist" aria-label="Filter platform">
                <button
                  role="tab"
                  aria-selected={platform == null}
                  className={platform == null ? "active" : ""}
                  onClick={() => setPlatform(null)}
                >
                  Semua platform
                </button>
                {platforms.map((pf) => (
                  <button
                    key={pf}
                    role="tab"
                    aria-selected={platform === pf}
                    className={platform === pf ? "active" : ""}
                    onClick={() => setPlatform(platform === pf ? null : pf)}
                  >
                    {pf === "instagram" ? "Instagram" : pf === "threads" ? "Threads" : pf}
                    <span className="count">{platformCounts[pf]}</span>
                  </button>
                ))}
              </div>
            )}
            <input
              className="search"
              type="search"
              placeholder="Cari teks atau akun…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {hasFilter && (
            <div className="active-filters">
              {platform && <Chip onRemove={() => setPlatform(null)}>Platform: {platform}</Chip>}
              {location && <Chip onRemove={() => setLocation(null)}>Lokasi: {location}</Chip>}
              {issue && <Chip onRemove={() => setIssue(null)}>Isu: {issue}</Chip>}
              {search && <Chip onRemove={() => setSearch("")}>“{search}”</Chip>}
              <button className="link" onClick={clearFilters}>Hapus filter</button>
            </div>
          )}

          {!loading && !error && visible.length === 0 && (
            <div className="empty">
              {posts.length === 0 ? (
                "Belum ada data. Jalankan pipeline dulu: uv run python -m pipeline.run"
              ) : view === "relevant" ? (
                <>
                  <p>
                    <strong>Belum ada posting relevan.</strong>
                    <br />
                    {stats.pending > 0
                      ? `${stats.pending} posting masih menunggu dinilai AI.`
                      : "AI sudah menilai semua posting, tapi belum ada yang lolos sebagai isu publik — label AI masih tahap awal."}
                  </p>
                  <button className="btn" onClick={() => setView("all")}>
                    Lihat semua {stats.total} posting
                  </button>
                </>
              ) : (
                "Tidak ada posting yang cocok dengan filter ini."
              )}
            </div>
          )}

          <ul className="posts">
            {visible.map((p) => (
              <PostCard key={p.id} post={p} onLocation={setLocation} onIssue={setIssue} />
            ))}
          </ul>
        </main>

        <aside>
          <Breakdown title="Lokasi" rows={locations} selected={location} onSelect={setLocation} />
          <Breakdown title="Isu" rows={issues} selected={issue} onSelect={setIssue} />
          <p className="aside-note">Dihitung dari posting yang sudah dianalisis. Klik untuk memfilter.</p>
        </aside>
      </div>
        </>
      )}
    </div>
  );
}

function EventsPage() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // null = semua; angka = HANYA urgency itu (bukan kumulatif), supaya 4 tidak ikut di 1
  const [urgency, setUrgency] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetch(`${API}/events?limit=200`)
      .then((r) => {
        if (!r.ok) throw new Error(`API ${r.status}`);
        return r.json();
      })
      .then((data) => active && setEvents(data))
      .catch((e) => active && setError(`Gagal memuat event (${e.message}). Jalankan: uv run python -m graph.run insight`))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const countBy = useMemo(() => {
    const c = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
    for (const e of events) c[Math.min(5, Math.max(1, e.urgency ?? 1))] += 1;
    return c;
  }, [events]);
  const visible = urgency == null ? events : events.filter((e) => (e.urgency ?? 1) === urgency);
  const urgent = countBy[4] + countBy[5];

  return (
    <>
      <section className="funnel" aria-label="Ringkasan event">
        <Stat label="Event" value={events.length} hint="hasil clustering hari ini" />
        <Stat label="Urgency 4–5" value={urgent} hint="perlu perhatian segera" tone="good" />
        <Stat
          label="Posting pendukung"
          value={events.reduce((n, e) => n + (e.post_count ?? 0), 0)}
          hint="termasuk balasan warga"
        />
      </section>

      <div className="toolbar">
        <div className="segmented" role="tablist" aria-label="Filter urgency">
          <button
            role="tab"
            aria-selected={urgency == null}
            className={urgency == null ? "active" : ""}
            onClick={() => setUrgency(null)}
          >
            Semua<span className="count">{events.length}</span>
          </button>
          {[5, 4, 3, 2, 1].map((u) => (
            <button
              key={u}
              role="tab"
              aria-selected={urgency === u}
              className={urgency === u ? "active" : ""}
              onClick={() => setUrgency(urgency === u ? null : u)}
              title={`Hanya event dengan urgency ${u}`}
            >
              <span className={`urgency u${u} mini`}>{u}</span>
              <span className="count">{countBy[u]}</span>
            </button>
          ))}
        </div>
      </div>

      {error && <div className="alert">{error}</div>}
      {loading && <div className="empty">Memuat event…</div>}
      {!loading && !error && events.length === 0 && (
        <div className="empty">
          Belum ada event. Jalankan <code>uv run python -m graph.run insight --date today</code> setelah pipeline.
        </div>
      )}
      {!loading && !error && events.length > 0 && visible.length === 0 && (
        <div className="empty">Tidak ada event dengan urgency {urgency}.</div>
      )}

      <ul className="events">
        {visible.map((e) => (
          <EventCard key={e.id} event={e} />
        ))}
      </ul>
    </>
  );
}

function EventCard({ event }) {
  const level = Math.min(5, Math.max(1, event.urgency ?? 1));
  return (
    <li className="event">
      <div className="event-head">
        <span className={`urgency u${level}`} title={`Urgency ${level}/5`}>
          {level}/5
        </span>
        <span className="issue">{event.issue_class}</span>
        {event.location && <span className="tag static">{event.location}</span>}
        <span className="muted">
          {event.post_count} posting · {event.window_date}
        </span>
      </div>

      {event.narrative?.title && <h3 className="event-title">{event.narrative.title}</h3>}
      <p className="event-rationale">{event.narrative?.summary || event.rationale}</p>
      {event.narrative && (
        <p className="event-meta muted">
          Sentimen {event.narrative.sentiment ?? "-"} · perhatian {event.narrative.attention_level ?? "-"} ·
          status {event.narrative.status ?? "-"}
        </p>
      )}

      <ul className="event-posts">
        {(event.posts ?? []).map((p) => (
          <li key={p.id} className={p.kind === "reply" ? "reply" : ""}>
            <span className="post-text">{p.text}</span>
            <div className="post-foot">
              <span>
                {p.platform}
                {p.author ? ` · @${p.author}` : ""}
                {p.kind === "reply" ? " · balasan" : ""}
                {p.topic_tag ? ` · #${p.topic_tag}` : ""}
                {formatTime(p.published_at) ? ` · ${formatTime(p.published_at)}` : ""}
              </span>
              {p.url ? (
                <a href={p.url} target="_blank" rel="noreferrer">Sumber ↗</a>
              ) : (
                <span className="muted">Tanpa URL</span>
              )}
            </div>
            {p.kind === "reply" && p.parent_url && (
              <a className="muted parent" href={p.parent_url} target="_blank" rel="noreferrer">
                ↑ lihat posting induk
              </a>
            )}
          </li>
        ))}
      </ul>
    </li>
  );
}

function ReportsPage() {
  const [reports, setReports] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(keep = null) {
    setLoading(true);
    try {
      const res = await fetch(`${API}/reports`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setReports(data);
      const target = data.find((r) => r.id === keep) ?? data.find((r) => r.id === selected) ?? data[0];
      setSelected(target ?? null);
    } catch (e) {
      setError(`Gagal memuat laporan (${e.message}).`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function approve() {
    if (!selected) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/reports/${selected.id}/approve`, { method: "POST" });
      if (!res.ok) throw new Error(`API ${res.status}`);
      await load(selected.id);
    } catch (e) {
      setError(`Gagal menyetujui (${e.message}).`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="reports">
      <aside className="report-list">
        <h2>Laporan</h2>
        {loading && <p className="muted">Memuat…</p>}
        {!loading && reports.length === 0 && (
          <p className="muted">Belum ada draf. Jalankan graph.run insight.</p>
        )}
        <ul>
          {reports.map((r) => (
            <li key={r.id}>
              <button
                className={`report-item ${selected?.id === r.id ? "active" : ""}`}
                onClick={() => setSelected(r)}
              >
                <span>{r.period}</span>
                <span className={`badge ${r.status}`}>{r.status}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="report-detail">
        {error && <div className="alert">{error}</div>}
        {!selected && !loading && <div className="empty">Pilih laporan di kiri.</div>}
        {selected && (
          <>
            <div className="report-head">
              <div>
                <h2>Laporan {selected.period}</h2>
                <span className="muted">
                  {selected.event_count} event · dibuat {formatTime(selected.created_at)}
                  {selected.approved_at ? ` · disetujui ${formatTime(selected.approved_at)}` : ""}
                </span>
              </div>
              <div className="report-actions">
                <span className={`badge ${selected.status}`}>{selected.status}</span>
                <a
                  className="btn"
                  href={`${API}/reports/${selected.id}.pdf`}
                  target="_blank"
                  rel="noreferrer"
                  title="PDF untuk dibagikan — tanpa bagian Rekomendasi"
                >
                  Unduh PDF
                </a>
                {selected.status === "draft" ? (
                  <button className="btn primary" onClick={approve} disabled={busy}>
                    {busy ? "Menyimpan…" : "Setujui"}
                  </button>
                ) : (
                  <span className="muted">Sudah disetujui</span>
                )}
              </div>
            </div>
            <article className="markdown">
              <Markdown source={selected.body_md} />
            </article>
          </>
        )}
      </main>
    </div>
  );
}

// Renderer markdown ringan (heading, list, bold, link) — cukup untuk draf laporan.
function Markdown({ source }) {
  const blocks = useMemo(() => (source ?? "").split("\n"), [source]);
  const inline = (text, keyPrefix) => {
    const parts = [];
    const re = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
    let last = 0;
    let m;
    let i = 0;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) parts.push(text.slice(last, m.index));
      const token = m[0];
      const key = `${keyPrefix}-${i++}`;
      if (token.startsWith("**")) {
        parts.push(<strong key={key}>{token.slice(2, -2)}</strong>);
      } else {
        const [, label, href] = token.match(/\[([^\]]+)\]\(([^)]+)\)/);
        parts.push(
          <a key={key} href={href} target="_blank" rel="noreferrer">
            {label}
          </a>,
        );
      }
      last = m.index + token.length;
    }
    if (last < text.length) parts.push(text.slice(last));
    return parts;
  };

  return (
    <>
      {blocks.map((line, i) => {
        const t = line.trim();
        if (!t) return null;
        if (t.startsWith("### ")) return <h4 key={i}>{inline(t.slice(4), `h${i}`)}</h4>;
        if (t.startsWith("## ")) return <h3 key={i}>{inline(t.slice(3), `h${i}`)}</h3>;
        if (t.startsWith("# ")) return <h2 key={i}>{inline(t.slice(2), `h${i}`)}</h2>;
        if (/^[-*]\s/.test(t)) {
          const indent = /^\s{2,}/.test(line);
          const text = t.replace(/^[-*]\s*/, "");
          return (
            <li key={i} className={indent ? "sub" : ""}>
              {inline(text, `l${i}`)}
            </li>
          );
        }
        if (t.startsWith("_") && t.endsWith("_")) {
          return (
            <p key={i} className="muted em">
              {t.slice(1, -1)}
            </p>
          );
        }
        return <p key={i}>{inline(t, `p${i}`)}</p>;
      })}
    </>
  );
}

function Stat({ label, value, hint, tone }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="stat-hint">{hint}</span>
    </div>
  );
}

function Chip({ children, onRemove }) {
  return (
    <span className="chip">
      {children}
      <button aria-label="Hapus filter" onClick={onRemove}>×</button>
    </span>
  );
}

function Breakdown({ title, rows, selected, onSelect }) {
  const max = rows[0]?.[1] ?? 1;
  return (
    <section className="panel">
      <h2>{title}</h2>
      {rows.length === 0 && <p className="muted">Belum ada.</p>}
      {rows.slice(0, 8).map(([name, count]) => (
        <button
          key={name}
          className={`bar-row ${selected === name ? "selected" : ""}`}
          onClick={() => onSelect(selected === name ? null : name)}
        >
          <span className="bar-fill" style={{ width: `${(count / max) * 100}%` }} />
          <span className="bar-name">{name}</span>
          <span className="bar-count">{count}</span>
        </button>
      ))}
    </section>
  );
}

function PostCard({ post, onLocation, onIssue }) {
  const status = statusOf(post);
  const time = formatTime(post.published_at ?? post.collected_at);
  const score = post.relevance_score;

  return (
    <li className={`post ${status}`}>
      <div className="post-head">
        <span className={`status ${status}`}>
          {status === "relevant" ? "Relevan" : status === "noise" ? "Tidak relevan" : "Menunggu AI"}
        </span>
        {post.kind === "reply" && <span className="tag static">balasan</span>}
        {post.kind === "tag" && <span className="tag static">tag #{post.topic_tag ?? ""}</span>}
        {post.location && (
          <button className="tag" onClick={() => onLocation(post.location)}>{post.location}</button>
        )}
        {post.issue_hint && (
          <button className="tag" onClick={() => onIssue(post.issue_hint)}>{post.issue_hint}</button>
        )}
        {score != null && (
          <span className="score" title="Skor relevansi dari AI">
            <span className="score-track">
              <span className="score-fill" style={{ width: `${score * 100}%` }} />
            </span>
            {score.toFixed(2)}
          </span>
        )}
      </div>

      <p className="post-text">{post.text}</p>
      {post.kind === "reply" && post.parent_url && (
        <a className="muted parent" href={post.parent_url} target="_blank" rel="noreferrer">
          ↑ balasan atas posting @{post.author} — lihat induknya
        </a>
      )}
      {post.reason && <p className="post-reason">AI: {post.reason}</p>}

      <div className="post-foot">
        <span>
          {post.platform}
          {post.author ? ` · @${post.author}` : ""}
          {time ? ` · ${time}` : ""}
        </span>
        {post.url ? (
          <a href={post.url} target="_blank" rel="noreferrer">Buka sumber asli ↗</a>
        ) : (
          <span className="muted">Tanpa URL sumber</span>
        )}
      </div>
    </li>
  );
}
