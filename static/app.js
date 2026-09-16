const $ = (id) => document.getElementById(id);

const geo = { lat: null, lon: null, status: "unknown", watchId: null };

// Current user identity — the journal (and future calls) use this instead of
// a hardcoded "demo". Seed with the browser's stored id, default demo.
const USER_ID = localStorage.getItem("moodos.user_id") || "demo";

let fadeObserver = null;

function observeFadeScroll() {
  const targets = document.querySelectorAll(".fade-scroll:not(.is-visible)");
  if (!targets.length) return;
  if (!fadeObserver) {
    fadeObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            fadeObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );
  }
  targets.forEach((t) => fadeObserver.observe(t));
}

function setHere(text) {
  const el = $("here");
  if (el) el.textContent = text;
}

function showLocationUnavailable(msg) {
  geo.status = "unavailable";
  setHere(msg || "Location unavailable");
  if (geo.watchId !== null) {
    navigator.geolocation.clearWatch(geo.watchId);
    geo.watchId = null;
  }
}

function requestGeo() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      showLocationUnavailable("Location unavailable");
      resolve();
      return;
    }
    // If we already have a live fix, reuse it instead of asking again.
    if (geo.status === "live" && geo.lat !== null) {
      resolve();
      return;
    }
    // Continuous live tracking: updates as the user moves.
    geo.watchId = navigator.geolocation.watchPosition(
      (pos) => {
        geo.lat = pos.coords.latitude;
        geo.lon = pos.coords.longitude;
        geo.status = "live";
        if (pos.coords.accuracy !== undefined) {
          setHere(`Live location ${geo.lat.toFixed(4)}, ${geo.lon.toFixed(4)} (${Math.round(pos.coords.accuracy)}m)`);
        } else {
          setHere(`Live location ${geo.lat.toFixed(4)}, ${geo.lon.toFixed(4)}`);
        }
        resolve();
      },
      (err) => {
        console.warn("Geolocation error:", err.code, err.message);
        if (err.code === 1) {
          // Permission denied — provide a manual retry, but no template fallback.
          showLocationUnavailable("Location unavailable — permission denied. " +
            "<button id='retryGeo' class='retry-geo'>Retry</button>");
          const btn = document.getElementById("retryGeo");
          if (btn) btn.onclick = () => { geo.status = "unknown"; setHere("Asking for location…"); requestGeo(); };
        } else if (err.code === 2) {
          showLocationUnavailable("Location unavailable — no GPS signal");
        } else {
          showLocationUnavailable("Location unavailable — request timed out. " +
            "<button id='retryGeo' class='retry-geo'>Retry</button>");
          const btn = document.getElementById("retryGeo");
          if (btn) btn.onclick = () => { geo.status = "unknown"; setHere("Asking for location…"); requestGeo(); };
        }
        resolve();
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 0 }
    );
  });
}

const agentChip = (label, on) => `<span class="chip${on ? " on" : ""}">${label}</span>`;

async function health() {
  try {
    const h = await fetch("/api/health").then((r) => r.json());
    const chips = [agentChip("Groq", h.groq), agentChip("Gemini", h.gemini)];
    if (h.mem0) chips.push(agentChip("Mem0 cloud", true));
    chips.push(agentChip("Spotify" + (h.spotify_user ? " +user" : ""), h.spotify));
    $("keys").innerHTML = chips.join("");
  } catch {
    $("keys").textContent = "backend offline";
  }
}

function sourceName(src) {
  return { gps: "live GPS", ip: "IP", user: "your input", default: "default" }[src] || src;
}

let _publicIp = null;
async function getPublicIp() {
  if (_publicIp) return _publicIp;
  try {
    const j = await fetch("https://api.ipify.org?format=json").then((r) => r.json());
    _publicIp = j.ip || null;
  } catch {
    _publicIp = null;
  }
  return _publicIp;
}

async function resolveLocation() {
  const userLabel = ($("loc").value || "").trim();
  const ip = await getPublicIp();
  const body = { lat: geo.lat, lon: geo.lon, user_label: userLabel || null, ip };
  try {
    const r = await fetch("/api/location/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) return null;
    const res = await r.json();
    if (res && res.city) {
      const conf = Math.round(res.confidence * 100);
      const extra = [res.area, res.state].filter(Boolean).join(", ");
      setHere(
        `📍 ${extra ? extra + ", " : ""}${res.city} · via ${sourceName(res.source)} · ${conf}% sure`
      );
    }
    return res;
  } catch {
    return null;
  }
}


function renderRestaurantCard(r) {
  const cuisineTags = (r.cuisine || "").split(",").filter(Boolean).map(
    (c) => `<span class="r-cuisine">${c.trim()}</span>`
  ).join("");
  const dietaryTags = r.dietary ? Object.keys(r.dietary).map(
    (d) => `<span class="r-dietary">${d}</span>`
  ).join("") : "";
  const meta = [];
  if (r.distance_label) meta.push(`<span>${r.distance_label}</span>`);
  else if (r.lat && r.lon) meta.push(`<span>📍</span>`);
  if (r.opening_hours) meta.push(`<span>🕐 ${r.opening_hours}</span>`);
  if (r.estimated_cost) meta.push(`<span>~₹${r.estimated_cost}</span>`);
  if (r.outdoor) meta.push(`<span>Outdoor seating</span>`);
  return `<div class="restaurant-card">
    <div class="r-name">${r.title}</div>
    <div>${cuisineTags}${dietaryTags}</div>
    <div class="r-meta">${meta.join("")}</div>
  </div>`;
}

function renderRestaurants(restaurants) {
  if (!restaurants || !restaurants.length) return "";
  const cards = restaurants.slice(0, 6).map(renderRestaurantCard).join("");
  return `<div class="restaurant-section fade-scroll">
    <h3>🍽️ Nearby Restaurants</h3>
    <div class="restaurant-grid">${cards}</div>
  </div>`;
}

function renderStreamingCard(m) {
  const streamBadges = (m.streaming || []).map(
    (s) => `<span class="r-cuisine">${s}</span>`
  ).join("");
  const vote = m.vote ? `⭐ ${Number(m.vote).toFixed(1)}` : "";
  return `<div class="restaurant-card streaming-card">
    <div class="r-name">🎬 ${m.title}</div>
    <div>${streamBadges}</div>
    <div class="r-meta">${vote ? `<span>${vote}</span>` : ""}${m.release_date ? `<span>${m.release_date.slice(0, 4)}</span>` : ""}${m.duration_min ? `<span>${m.duration_min} min</span>` : ""}<span>₹0 (streaming)</span></div>
    ${m.text ? `<p class="why">${m.text.slice(0, 120)}${m.text.length > 120 ? "…" : ""}</p>` : ""}
    ${m.watch_link ? `<a href="${m.watch_link}" target="_blank" class="tiny">Where to watch →</a>` : ""}
  </div>`;
}

function renderStreamingMovies(movies) {
  if (!movies || !movies.length) return "";
  const cards = movies.slice(0, 6).map(renderStreamingCard).join("");
  return `<div class="restaurant-section fade-scroll">
    <h3>🎬 Watch at Home</h3>
    <div class="restaurant-grid">${cards}</div>
  </div>`;
}

function renderToolUsage(data) {
  const tu = data.tool_usage;
  if (!tu) return "";
  const labels = {
    weather: "Weather",
    places: "Cafés / walk",
    restaurants: "Restaurants",
    cinemas: "Cinemas",
    movies: "Movies",
    music: "Music",
    books: "Books",
    knowledge: "Knowledge",
    memory: "Your profile",
  };
  const rows = Object.keys(tu)
    .filter((k) => tu[k])
    .map((k, i) => {
      const t = tu[k];
      return `<tr class="${i % 2 ? "tools-row-alt" : ""}">
        <td>${labels[k] || k}</td>
        <td>${t.tool || "—"}</td>
        <td>${t.source || ""}</td>
      </tr>`;
    })
    .join("");
  return `<details class="tools-section fade-scroll">
    <summary class="tools-header">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="6"/><path d="M7 4v3.5l2 1.5"/></svg>
      <span class="tools-header-label">Which tools and data sources were used?</span>
      <span class="tools-chevron">⌃</span>
    </summary>
    <table class="tools-table">
      <tbody>${rows}</tbody>
    </table>
  </details>`;
}

function renderChat(data) {
  $("result").classList.remove("hidden");
  $("result").innerHTML = `
    <div class="result-card">
      <div class="bundle-eyebrow">Direct answer</div>
      <div class="bundle-title">MoodOS</div>
      <div class="bundle-desc">${data.reply || ""}</div>
    </div>
  `;
}

const travelVerb = (mode) => ({ walk: "Walk", drive: "Drive", transit: "Take transit" }[mode] || "Travel");

const badgeLabel = (kind) =>
  ({ cafe: "café", restaurant: "restaurant", food: "food", movie: "movie", music: "music", rest: "rest", streaming: "home", walk: "walk" }[kind] || kind || "step");

function stepMeta(s) {
  if (s.kind === "travel") return [];
  const m = [`${s.duration_min || 0} min`];
  m.push(priceMeta(s) || `₹${s.cost_inr || 0}`);
  const g = genreMeta(s);
  if (g) m.push(g.replace(/^ · /, ""));
  const r = runtimeMeta(s);
  if (r) m.push(r.replace(/^ · /, ""));
  if (s.distance_label) m.push(s.distance_label + (s.walk_min ? ` (~${s.walk_min} min walk)` : ""));
  if (s.kind !== "movie" && s.flexible === false) m.push("fixed");
  return m;
}

function stepWarnings(s) {
  const out = [];
  if (s.kind === "movie") {
    const bits = [];
    if (!(Array.isArray(s.genres) && s.genres.length) && !s.mood_fit_verified) bits.push("Genre and tone unverified from listing.");
    if (s.is_estimate || s.runtime_source === "estimate") bits.push("Treat runtime as an estimate.");
    if (bits.length) out.push(bits.join(" "));
  }
  if (s.opening_note && String(s.opening_note).includes("closed")) out.push(`⏳ ${s.opening_note}`);
  return out;
}

function runtimeMeta(s) {
  if (s.kind !== "movie") return "";
  if (s.runtime_source === "tmdb") return " · real runtime from TMDB";
  if (s.is_estimate || s.runtime_source === "estimate") return " · est. runtime";
  return "";
}

function showtimeDisclaimer(s) {
  if (s.kind !== "movie" || !s.showtime_estimated) return "";
  const note = s.showtime_disclaimer ||
    `Showtime is an estimate — check ${s.venue || "the cinema"} for exact timing.`;
  return `<p class="t-warning">⏱ ${note}</p>`;
}

function genreMeta(s) {
  if (s.kind !== "movie") return "";
  const genres = Array.isArray(s.genres) && s.genres.length ? s.genres.join(", ") : null;
  const fit = s.genre_fit || "unknown";
  const verified = !!s.mood_fit_verified;
  if (!genres) {
    return verified ? "" : " · genre/tone unverified";
  }
  const fitTag = verified
    ? (fit === "poor" ? "· intense" : fit === "neutral" ? "· neutral tone" : "· light fit")
    : "";
  return ` · ${genres}${fitTag}`;
}

function priceMeta(s) {
  if (s.kind === "movie" || s.kind === "travel" || s.kind === "music" || s.kind === "streaming") return "";
  if (s.price_is_estimate) {
    return ` · est. ₹${s.cost_inr || 0}${s.price_tier ? ` (${s.price_tier})` : ""}`;
  }
  return "";
}

function renderStep(s) {
  if (s.kind === "travel") {
    const dist = s.distance_label || (s.distance_km != null ? s.distance_km + " km" : "");
    const meta = [
      `${s.duration_min || 0} min`,
      `₹${s.cost_inr || 0}`,
      s.flexible === false ? "fixed (routing)" : "",
      dist,
    ].filter(Boolean).join(" · ");
    return `<div class="t-item fade-scroll" data-kind="travel">
      <div class="t-node travel">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 8h10M9 5l4 3-4 3"/></svg>
      </div>
      <div class="t-body">
        <div class="t-card travel-card">
          <div class="t-travel-title">${travelVerb(s.mode)}${s.to ? " to " + s.to : ""}</div>
          <div class="t-desc travel-desc">${meta}</div>
        </div>
      </div>
    </div>`;
  }
  const warns = stepWarnings(s);
  const tracks = Array.isArray(s.tracks) ? s.tracks.slice(0, 5) : [];
  const trackList = tracks.length
    ? `<div class="pl-list pl-inline">${tracks.map((t, i) => `
        <div class="pl-track">
          <span class="pl-idx">${i + 1}</span>
          <span class="pl-title">${t.title}</span>
          <span class="pl-dur">${fmtDur(t)}</span>
        </div>`).join("")}</div>
      <div class="tiny">${s.tracks_source || ""}</div>`
    : "";
  return `<div class="t-item fade-scroll" data-kind="${s.kind || ""}">
    <div class="t-node activity">${s.order ?? ""}</div>
    <div class="t-body">
      <div class="t-card">
        <div class="t-card-head">
          <div>
            <div class="t-title">${s.title}</div>
            <div class="t-meta-row">${stepMeta(s).map((m) => `<span>${m}</span>`).join("")}</div>
          </div>
          <div class="t-type-badge ${s.kind || ""}">${badgeLabel(s.kind)}</div>
        </div>
        <div class="t-desc">${s.why || ""}</div>
        ${s.kind === "movie" && ((Array.isArray(s.streaming) && s.streaming.length) || s.watch_link)
          ? `<div class="t-home-note">${Array.isArray(s.streaming) && s.streaming.length
              ? `🏠 Also streaming at home on ${s.streaming.join(", ")}${s.watch_link ? ` · <a href="${s.watch_link}" target="_blank" class="tiny">watch link →</a>` : ""}`
              : `🏠 Also watchable at home · <a href="${s.watch_link}" target="_blank" class="tiny">find where to watch →</a>`}</div>`
          : ""}
        ${trackList}
        ${warns.map((w) => `<div class="t-warning">${w}</div>`).join("")}
        ${showtimeDisclaimer(s)}
      </div>
    </div>
  </div>`;
}

function fmtDur(t) {
  if (t.duration_sec) {
    const m = Math.floor(t.duration_sec / 60);
    const s = String(t.duration_sec % 60).padStart(2, "0");
    return `${m}:${s}`;
  }
  if (t.duration_min) return `${t.duration_min} min`;
  return "";
}

function renderPlan(data) {
  const plan = data.plan || {};
  const slots = data.slots || {};
  const stayHome = data.stay_home || false;
  const steps = (plan.steps || []).map(renderStep).join("");
  const weather = (data.weather?.condition || "—") +
    (data.weather?.temperature_c != null ? " " + data.weather.temperature_c + "°" : "");
  const place = stayHome
    ? "staying in"
    : (data.location?.label
        ? data.location.label + (data.location.state_label ? ", " + data.location.state_label : "")
        : (geo.status === "live" ? "Live position" : "Unavailable"));
  const metaVal = (v) => v || "—";

  $("result").classList.remove("hidden");
  $("result").innerHTML = `
    <div class="bundle-header fade-scroll">
      <div class="bundle-eyebrow">Experience plan ready</div>
      <div class="bundle-title">${stayHome ? "A Cozy Night In, Curated" : "Your Evening, Curated"}</div>
      <div class="bundle-desc">${plan.explanation || ""}</div>
    </div>

    <div class="meta-grid fade-scroll">
      <div class="meta-cell">
        <div class="meta-label">Mood</div>
        <div class="meta-value mood">${metaVal(slots.current_mood)}</div>
      </div>
      <div class="meta-cell">
        <div class="meta-label">Desired</div>
        <div class="meta-value desired">${metaVal(slots.desired_mood)}</div>
      </div>
      <div class="meta-cell">
        <div class="meta-label">Budget</div>
        <div class="meta-value">${slots.budget_inr != null ? "₹" + slots.budget_inr : "—"}</div>
      </div>
      <div class="meta-cell">
        <div class="meta-label">Time</div>
        <div class="meta-value">${slots.duration_hours ? slots.duration_hours + " hours" : "—"}</div>
      </div>
      <div class="meta-cell">
        <div class="meta-label">Social</div>
        <div class="meta-value">${metaVal(slots.social)}</div>
      </div>
      <div class="meta-cell">
        <div class="meta-label">Weather · Place</div>
        <div class="meta-value place">${metaVal(weather)} · ${metaVal(place)}</div>
      </div>
    </div>

    <div class="timeline fade-scroll">
      ${steps}
    </div>

    <div class="total-bar fade-scroll">
      <div>
        <div class="total-label">Estimated spend</div>
        <div class="total-amount">₹${plan.total_cost_inr ?? "—"}</div>
      </div>
      <div class="total-time">
        <div class="total-label">Total time</div>
        <div class="total-amount">${plan.total_duration_min ?? "—"} min</div>
      </div>
      <div>
        <div class="total-label">You asked for</div>
        <div style="font-size:13px; color: var(--text-m);">~${plan.requested_minutes ?? "—"} min${slots.budget_inr != null ? " · ₹" + slots.budget_inr + " budget" : ""}</div>
      </div>
    </div>

    ${renderToolUsage(data)}
    ${stayHome ? renderStreamingMovies(data.streaming_movies) : renderRestaurants(data.restaurants)}

    <div class="action-row fade-scroll">
      <button class="btn-action btn-primary-action" type="button" id="like">That was perfect</button>
      ${stayHome ? '' : '<button class="btn-action btn-secondary-action" type="button" id="prep">Prepare movie booking</button>'}
      <button class="btn-action btn-secondary-action" type="button" id="plist">Create Spotify playlist</button>
      ${stayHome ? '' : '<button class="btn-action btn-secondary-action" type="button" id="findFood">Find restaurants</button>'}
    </div>
    <div id="book"></div>
  `;
  observeFadeScroll();

  $("like").onclick = async () => {
    const slots = data.slots || {};
    const plan = data.plan || {};
    const kinds = (plan.steps || []).map((s) => s.kind).filter(Boolean);
    const activityList = [...new Set(kinds.filter((k) => k !== "travel"))].join(", ") || "evening out";
    const note = [
      `Enjoyed a ${slots.duration_hours || "?"}h ${activityList} experience`,
      slots.current_mood ? `Mood: ${slots.current_mood} → ${slots.desired_mood || "?"}` : "",
      slots.social ? `Social: ${slots.social}` : "",
    ].filter(Boolean).join("; ");
    $("like").textContent = "Saving…";
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_id: data.event_id,
          signal: "like",
          note,
          repeats: 2,
        }),
      }).then((r) => r.json());
      $("like").textContent = res.new
        ? "Stored in Mem0"
        : "Already remembered";
    } catch {
      $("like").textContent = "Couldn't store";
    }
  };

  if ($("prep")) {
    $("prep").onclick = async () => {
      const prep = await fetch("/api/booking/prepare", { method: "POST" }).then((r) => r.json());
      const show = prep.show || {};
      $("book").innerHTML = `
        <p><strong>Prepared (not charged)</strong> · ${show.cinema} · ${show.movie} · ${show.time} · ₹${show.price_inr}</p>
        <button type="button" id="confirm">I confirm this paid mock booking</button>
      `;
      $("confirm").onclick = async () => {
        const done = await fetch("/api/booking/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmed: true, show_index: 0 }),
        }).then((r) => r.json());
        $("book").innerHTML += `<p class="tiny">Executed via ${done.provider} · code ${done.confirmation_code}</p>`;
      };
    };
  }

  $("plist").onclick = () => renderPlaylistPanel(0);

  function renderPlaylistPanel(seed) {
    const q = data.music_query || "calm acoustic evening";
    $("book").innerHTML = `<p class="tiny">Mood-based picks for “${q}”…</p>`;
    fetch(`/api/playlist/prepare?query=${encodeURIComponent(q)}&seed=${seed}`, { method: "POST" })
      .then((r) => r.json())
      .then((prep) => {
        const tracks = (prep.tracks || []).slice(0, 8);
        const fmt = (sec) => {
          if (!sec) return "—";
          const m = Math.floor(sec / 60);
          const s = String(sec % 60).padStart(2, "0");
          return `${m}:${s}`;
        };
        const rows = tracks.map(
          (t, i) => `
          <div class="pl-track">
            <span class="pl-idx">${i + 1}</span>
            <span class="pl-title">${t.title}</span>
            <span class="pl-dur">${fmt(t.duration_sec)}</span>
          </div>`
        ).join("");
        const totalSec = tracks.reduce((n, t) => n + (t.duration_sec || 0), 0);
        const totalMin = totalSec ? Math.round(totalSec / 60) : 0;
        let extra = "";
        if (!prep.spotify_connected && prep.authorize_url) {
          extra = `<p><a href="/spotify/login">Connect Spotify first</a></p>`;
        }
        $("book").innerHTML = `
          <p><strong>Prepared playlist</strong> · based on your ${data.slots?.desired_mood || data.slots?.current_mood || "mood"}
            ${prep.seed > 0 ? `<span class="tiny">(refreshed #${seed + 1})</span>` : ""}</p>
          ${prep.provider ? `<p class="tiny">via ${prep.provider}${prep.provider === "itunes-search" ? " — Spotify search unavailable (needs Premium on the app-owner account)" : ""}</p>` : ""}
          <div class="pl-list">
            ${rows || `<p class="tiny">No tracks — try refreshing or adjusting your mood.</p>`}
          </div>
          ${rows ? `<div class="pl-summary"><span>${tracks.length} songs</span><span>${totalMin} min total</span></div>` : ""}
          ${extra}
          <button type="button" id="plrefresh">Refresh suggestions</button>
          <button type="button" id="plistgo">I confirm creating this playlist</button>
        `;
        $("plrefresh").onclick = () => renderPlaylistPanel(seed + 1);
        $("plistgo").onclick = async () => {
          const done = await fetch("/api/playlist/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: q, confirmed: true }),
          }).then((r) => r.json());
          $("book").innerHTML += `<p class="tiny">${done.status}${done.playlist_url ? " · " + done.playlist_url : ""}</p>`;
          const btn = document.getElementById("plistgo");
          if (btn) btn.disabled = true;
        };
      })
      .catch(() => {
        $("book").innerHTML = `<p class="tiny">Couldn't load suggestions. Try again.</p>`;
      });
  }

  if ($("findFood")) {
    $("findFood").onclick = async () => {
      const mood = data.slots?.desired_mood || data.slots?.current_mood || "";
      const params = new URLSearchParams();
      if (geo.lat) params.set("lat", geo.lat);
      if (geo.lon) params.set("lon", geo.lon);
      if (mood) params.set("mood", mood);
      params.set("limit", "8");
      const res = await fetch(`/api/restaurants?${params}`).then((r) => r.json());
      if (res.restaurants && res.restaurants.length) {
        $("book").innerHTML = renderRestaurants(res.restaurants);
      } else {
        $("book").innerHTML = `<p class="tiny">No restaurants found nearby. Try adjusting your location.</p>`;
      }
    };
  }
}

function render(data) {
  if (data.mode === "chat") renderChat(data);
  else renderPlan(data);
  window.__last = data;
}

$("go").onclick = async () => {
  $("status").classList.remove("hidden");
  $("result").classList.add("hidden");
  const userLabel = ($("loc").value || "").trim();
  if (!geo.lat && userLabel) {
    // No GPS but a manual location was typed — use it instead of waiting on GPS.
    geo.status = "user";
  }
  await requestGeo();
  const locNote = geo.status === "live"
    ? "Asking MoodOS…"
    : (userLabel || geo.status === "user")
      ? "Using your chosen location. Ask MoodOS…"
      : "No location found — using a default area. Ask MoodOS…";
  $("status").textContent = locNote + " (this can take ~30s)";
  const body = {
    message: $("msg").value,
    prompt: $("prompt").value || null,
    lat: geo.lat,
    lon: geo.lon,
    user_label: userLabel || null,
    ip: await getPublicIp(),
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90000);
  try {
    const res = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error("Server error " + res.status);
    const data = await res.json();
    $("status").textContent = data.mode === "chat" ? "Direct answer" : "Experience plan ready.";
    render(data);
  } catch (err) {
    console.error(err);
    $("status").textContent = "Something went wrong — the request timed out or the backend is unreachable.";
    $("result").classList.remove("hidden");
    $("result").innerHTML = `
      <div class="result-card">
        <div class="bundle-eyebrow">Could not build a plan</div>
        <div class="bundle-title">Oops</div>
        <div class="bundle-desc">Couldn't get an answer. Try again, or check that the server is running.</div>
      </div>
    `;
  } finally {
    clearTimeout(timer);
  }
};

health();

if ($("loc")) {
  let locTimer = null;
  $("loc").addEventListener("input", () => {
    clearTimeout(locTimer);
    if (($("loc").value || "").trim()) setHere("Resolving your chosen location…");
    locTimer = setTimeout(resolveLocation, 700);
  });
}

requestGeo().then(() => resolveLocation());

if ($("forget")) {
  $("forget").onclick = async () => {
    if (!confirm("Forget MoodOS's memory of you? This clears your saved preferences for this browser demo.")) return;
    const btn = $("forget");
    btn.disabled = true;
    btn.textContent = "Clearing…";
    try {
      const res = await fetch("/api/mem0/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: "demo" }),
      }).then((r) => r.json());
      btn.textContent = res.ok
        ? `Cleared (${res.cloud ? res.local + " local + cloud" : res.local + " memories"})`
        : "Couldn't clear";
    } catch {
      btn.textContent = "Couldn't clear";
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = "Forget my memory";
    }, 3000);
  };
}

// --- Memories modal --------------------------------------------------------
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const badgeClass = {
  preference: "pref",
  pattern: "pattern",
  feedback: "feedback",
  episodic: "episodic",
};

async function loadMemories() {
  const list = $("memories-list");
  list.innerHTML = '<div class="modal-empty">Loading…</div>';
  let rows = [];
  try {
    const res = await fetch("/api/mem0?user_id=demo&categories=").then((r) => r.json());
    rows = res.memories || [];
  } catch {
    list.innerHTML = '<div class="modal-empty">Couldn&#39;t load memories.</div>';
    return;
  }
  if (!rows.length) {
    list.innerHTML = '<div class="modal-empty">No memories yet — plans and likes build them over time.</div>';
    return;
  }
  list.innerHTML = "";
  for (const m of rows) {
    const cat = m.category || "preference";
    const createdAt = (m.created_at || "").slice(0, 10);
    const card = document.createElement("div");
    card.className = "memory-card";
    card.dataset.mid = m.id || "";
    card.innerHTML = `
      <div class="memory-row">
        <span class="memory-badge ${badgeClass[cat] || ""}">${esc(cat)}</span>
        <span class="memory-meta">
          ${createdAt ? `<span>${esc(createdAt)}</span>` : ""}
          <span>${esc(m.source || "mem0")}</span>
        </span>
      </div>
      <div class="memory-text">${esc(m.text)}</div>
      <div class="memory-actions">
        <button class="memory-btn" type="button" data-act="edit">Edit</button>
        <button class="memory-btn danger" type="button" data-act="del">Delete</button>
      </div>`;
    list.appendChild(card);
  }
}

async function deleteMemory(mid) {
  const res = await fetch("/api/mem0/" + encodeURIComponent(mid) + "?user_id=demo", { method: "DELETE" }).then((r) => r.json());
  loadMemories();
  return res.ok;
}

async function saveMemory(mid, text) {
  const res = await fetch("/api/mem0/" + encodeURIComponent(mid), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: "demo", text }),
  }).then((r) => r.json());
  loadMemories();
  return res.ok;
}

function openMemories() {
  $("memories-modal").classList.remove("hidden");
  loadMemories();
}

if ($("memories-btn")) {
  $("memories-btn").onclick = openMemories;
  $("memories-close").onclick = () => $("memories-modal").classList.add("hidden");
  $("memories-modal").addEventListener("click", (e) => {
    if (e.target.id === "memories-modal") $("memories-modal").classList.add("hidden");
  });
  $("memories-list").addEventListener("click", async (e) => {
    const act = e.target.dataset && e.target.dataset.act;
    const card = e.target.closest(".memory-card");
    if (!card || !act) return;
    const mid = card.dataset.mid;
    if (!mid) return;
    if (act === "del") {
      if (confirm("Delete this memory?")) deleteMemory(mid);
    } else if (act === "edit") {
      const text = card.querySelector(".memory-text").textContent;
      card.querySelector(".memory-text").outerHTML =
        `<textarea class="memory-edit-input" rows="2">${esc(text)}</textarea>`;
      e.target.textContent = "Save";
      e.target.dataset.act = "save";
      const input = card.querySelector(".memory-edit-input");
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    } else if (act === "save") {
      const input = card.querySelector(".memory-edit-input");
      const text = (input.value || "").trim();
      if (!text) return;
      e.target.disabled = true;
      await saveMemory(mid, text);
    }
  });
}

if ($("journal-btn")) {
  $("journal-btn").onclick = openJournal;
  $("journal-close").onclick = () => $("journal-modal").classList.add("hidden");
  $("journal-modal").addEventListener("click", (e) => {
    if (e.target.id === "journal-modal") $("journal-modal").classList.add("hidden");
  });
  $("journal-body").addEventListener("click", (e) => {
    const btn = e.target.closest(".jr-btn");
    if (!btn || btn.disabled || btn.dataset.react == null) return;
    const entryId = Number(btn.dataset.entry);
    const reaction = btn.dataset.react;
    if (entryId && reaction) reactToEntry(entryId, reaction);
  });
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const modal = $("memories-modal");
    if (modal && !modal.classList.contains("hidden")) modal.classList.add("hidden");
    const journal = $("journal-modal");
    if (journal && !journal.classList.contains("hidden")) journal.classList.add("hidden");
  }
});

// --- Mood Journal modal -----------------------------------------------------

function openJournal() {
  $("journal-modal").classList.remove("hidden");
  loadJournal();
}

async function loadJournal() {
  const body = $("journal-body");
  body.innerHTML = '<div class="modal-empty">Loading…</div>';
  let t = null, s = null;
  try {
    const [trendsRes, stripRes] = await Promise.all([
      fetch(`/api/journal/trends?user_id=${encodeURIComponent(USER_ID)}&weeks=4`),
      fetch(`/api/journal/strip?user_id=${encodeURIComponent(USER_ID)}&limit=12`),
    ]);
    if (!trendsRes.ok) throw new Error("http " + trendsRes.status);
    t = await trendsRes.json();
    s = stripRes.ok ? await stripRes.json() : { entries: [] };
  } catch {
    body.innerHTML = '<div class="modal-empty">Couldn&#39;t load your journal.</div>';
    return;
  }
  currentStrip = s;
  renderJournal(t, s);
}

function renderJournal(t, s) {
  const body = $("journal-body");
  const hint = $("journal-foot-hint");
  const total = (t && t.total_entries) || 0;
  if (!t || total === 0) {
    hint.textContent = "No entries yet — MoodOS writes one every time it plans an evening.";
    body.innerHTML = `
      <div class="journal-empty">
        <div class="journal-empty-title">Your mood journal is empty</div>
        <div class="journal-empty-sub">Every time MoodOS plans an evening it saves your mood, the weather, and the plan as a journal entry. Ask MoodOS to plan anything — trends and insights will appear here once you have a few.</div>
      </div>`;
    return;
  }
  hint.textContent = `${total} journal entr${total === 1 ? "y" : "ies"} recorded — updates automatically as you plan.`;
  body.innerHTML = `
    <div class="journal-section">
      ${renderInsight(t.insight)}
      ${renderPlanReactions(s)}
      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title">Mood over the last 4 weeks</div>
          <div class="chart-sub">Daily average mood valence · −1 low … +1 high</div>
          ${renderLineChart(t.heatmap)}
        </div>
        <div class="chart-card">
          <div class="chart-title">Weather and mood</div>
          <div class="chart-sub">Average mood on rainy vs clear days</div>
          ${renderWeather(t.weather)}
        </div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Daily mood heatmap</div>
        <div class="chart-sub">Last ${t.heatmap.weeks || 12} weeks · hover a day for details</div>
        ${renderHeatmap(t.heatmap)}
      </div>
    </div>`;
}

// --- journal reaction strip ------------------------------------------------

const REACTIONS = [
  { key: "happy", emoji: "😊", label: "Loved it" },
  { key: "neutral", emoji: "😐", label: "It was okay" },
  { key: "sad", emoji: "😞", label: "Missed the mark" },
];

let currentStrip = null;

function renderPlanReactions(s) {
  const entries = (s && s.entries) || [];
  if (!entries.length) return "";
  const rated = (s && s.rated_count) || 0;
  let sub;
  if (rated === entries.length) sub = "All of the last plans rated — new entries appear as you plan";
  else if (rated) sub = `${rated} of the last ${entries.length} plans already rated — feel free to rate the rest`;
  else sub = "Tap how each plan actually felt — once per plan";
  return `
    <div class="chart-card" id="jr-card">
      <div class="chart-title">How were these plans?</div>
      <div class="chart-sub" id="jr-sub">${sub}</div>
      <div class="jr-list">
        ${entries.map(reactionRow).join("")}
      </div>
    </div>`;
}

function reactionRow(entry) {
  const rated = !entry.reactable;
  const dateTxt = entry.local_date ? fmtDateShort(entry.local_date) : "";
  const btns = REACTIONS.map((r) => {
    const chosen = rated && entry.mood_reaction === r.key;
    const cls = ["jr-btn", chosen ? "on" : (rated ? "off" : "")].filter(Boolean).join(" ");
    const attrs = rated
      ? 'tabindex="-1" disabled aria-disabled="true"'
      : `data-react="${r.key}" aria-pressed="false"`;
    return `<button type="button" class="${cls}" data-entry="${entry.id}" ${attrs} title="${r.label}"><span class="jr-emoji">${r.emoji}</span><span class="jr-visr">${r.label}</span></button>`;
  }).join("");
  return `<div class="jr-row${rated ? " jr-rated" : ""}" data-entry="${entry.id}">
    <div class="jr-meta">
      ${dateTxt ? `<span class="jr-date">${dateTxt}</span>` : ""}
      ${entry.time_bucket ? `<span class="jr-bucket">${esc(entry.time_bucket)}</span>` : ""}
    </div>
    <div class="jr-line">${esc(entry.line)}</div>
    <div class="jr-actions">${btns}</div>
  </div>`;
}

function fmtDateShort(iso) {
  try {
    const d = parseDate(String(iso).slice(0, 10));
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  } catch { return iso; }
}

async function reactToEntry(entryId, reaction) {
  const body = $("journal-body");
  const row = body.querySelector(`.jr-row[data-entry="${entryId}"]`);
  if (row) row.classList.add("jr-pending");
  try {
    const res = await fetch("/api/journal/react", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID, entry_id: entryId, reaction }),
    });
    const data = await res.json();
    if (data && data.applied) {
      for (const it of currentStrip.entries) {
        if (it.id === entryId) {
          it.mood_reaction = reaction;
          it.reactable = false;
        }
      }
      currentStrip.rated_count += 1;
      const card = $("jr-card");
      if (card) card.innerHTML = renderPlanReactions(currentStrip);
      return;
    }
  } catch { /* fall through to a clean re-sync */ }
  await refreshStrip();
}

async function refreshStrip() {
  try {
    const res = await fetch(`/api/journal/strip?user_id=${encodeURIComponent(USER_ID)}&limit=12`);
    if (!res.ok) return;
    currentStrip = await res.json();
  } catch { currentStrip = null; }
  const card = $("jr-card");
  if (!card) return;
  const fresh = renderPlanReactions(currentStrip);
  if (fresh) card.innerHTML = fresh;
}

function renderInsight(ins) {
  const mark = `<div class="insight-mark">
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2 9l3-4 2.5 3.5L10 5l4 6"/><circle cx="12" cy="4" r="1.2" fill="currentColor"/></svg>
  </div>`;
  if (!ins || !ins.text) {
    return `<div class="insight-card">
      ${mark}
      <div>
        <span class="insight-chip">Impact</span>
        <div class="insight-text">No insights yet — generate a few more plans and I'll spot your patterns.</div>
      </div>
    </div>`;
  }
  const up = ins.kind === "mood_up";
  return `<div class="insight-card">
    ${mark}
    <div>
      <span class="insight-chip ${up ? "up" : ""}">${esc(String(ins.kind).replace(/_/g, " "))}</span>
      <div class="insight-text">${esc(ins.text)}</div>
    </div>
    <span class="insight-count">based on ${ins.sample_size} plans</span>
  </div>`;
}

// --- date + colour helpers ---------------------------------------------------

function parseDate(s) {
  const [y, m, d] = String(s).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}
function fmtDate(dt) { return dt.toISOString().slice(0, 10); }
function addDays(dt, n) { const d = new Date(dt); d.setUTCDate(d.getUTCDate() + n); return d; }
function dayDiff(a, b) { return Math.round((b - a) / 86400000); }

function isoWeek(dt) {
  const t = new Date(Date.UTC(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate()));
  const dow = (t.getUTCDay() + 6) % 7;
  t.setUTCDate(t.getUTCDate() - dow + 3);
  const firstThu = t.getTime();
  t.setUTCMonth(0, 1);
  if (t.getUTCDay() !== 4) t.setUTCMonth(0, 1 + ((4 - t.getUTCDay()) + 7) % 7);
  return 1 + Math.ceil((firstThu - t.getTime()) / 604800000);
}

function hexRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
function mix(hex1, hex2, t) {
  const c1 = hexRgb(hex1), c2 = hexRgb(hex2);
  return [
    Math.round(c1.r + (c2.r - c1.r) * t),
    Math.round(c1.g + (c2.g - c1.g) * t),
    Math.round(c1.b + (c2.b - c1.b) * t),
  ].join(", ");
}
// Amber base — positive blends toward emerald, negative toward brick.
function valenceFill(v) {
  if (v == null || isNaN(v)) return "";
  const t = Math.min(1, Math.abs(v));
  const a = (0.28 + 0.55 * t).toFixed(2);
  const rgb = v >= 0 ? mix("#c4883a", "#7a8a5e", t) : mix("#c4883a", "#b4642d", t);
  return `rgba(${rgb}, ${a})`;
}

// --- line chart (SVG) --------------------------------------------------------

function renderLineChart(hm) {
  const days = (hm.days || []).filter((d) => d.date && d.count > 0);
  if (!days.length) return '<p class="modal-empty">No mood data yet.</p>';
  const end = parseDate(hm.end || fmtDate(new Date()));
  const start4w = addDays(end, -27);

  const byIndex = {};
  for (const d of days) {
    const idx = dayDiff(start4w, parseDate(d.date));
    if (idx >= 0 && idx <= 27) byIndex[idx] = d;
  }

  const W = 560, H = 210, PL = 36, PR = 14, PT = 14, PB = 26;
  const iw = W - PL - PR, ih = H - PT - PB;
  const xScale = (i) => PL + (i / 27) * iw;
  const yScale = (v) => PT + (1 - (Math.min(1, Math.max(-1, v)) + 1) / 2) * ih;
  const y0 = yScale(0);
  const rnd = (n) => Math.round(n * 10) / 10;

  const pts = [];
  for (let i = 0; i < 28; i++) {
    const d = byIndex[i];
    pts.push(d
      ? { x: xScale(i), y: yScale(d.avg_valence), d }
      : null);
  }

  // Contiguous present days connect with a solid line; spans with one or more
  // missing days connect with a dashed segment so sparse weeks read as gaps,
  // not a broken chart. The area fill only paints contiguous runs.
  let area = "", runStart = null, lastPt = null;
  for (const p of pts) {
    if (p) {
      if (!lastPt) { area += `M ${rnd(p.x)} ${rnd(p.y)}`; runStart = p; }
      else { area += ` L ${rnd(p.x)} ${rnd(p.y)}`; }
      lastPt = p;
    } else if (lastPt) {
      area += ` L ${rnd(lastPt.x)} ${rnd(y0)} L ${rnd(runStart.x)} ${rnd(y0)} Z`;
      lastPt = null; runStart = null;
    }
  }
  if (lastPt) area += ` L ${rnd(lastPt.x)} ${rnd(y0)} L ${rnd(runStart.x)} ${rnd(y0)} Z`;

  const present = [];
  for (let i = 0; i < pts.length; i++) if (pts[i]) present.push({ ...pts[i], i });
  let line = "", dash = "", inRun = false;
  for (let k = 0; k + 1 < present.length; k++) {
    const a = present[k], b = present[k + 1];
    const dashed = (b.i - a.i) > 1;
    if (dashed) {
      inRun = false;
      dash += `M ${rnd(a.x)} ${rnd(a.y)} L ${rnd(b.x)} ${rnd(b.y)} `;
    } else {
      if (!inRun) { inRun = true; line += `M ${rnd(a.x)} ${rnd(a.y)}`; }
      line += ` L ${rnd(b.x)} ${rnd(b.y)}`;
    }
  }

  const grid = [];
  for (const v of [-1, -0.5, 0, 0.5, 1]) {
    grid.push(`<line class="${v === 0 ? "l-zero" : "l-grid"}" x1="${PL}" y1="${rnd(yScale(v))}" x2="${W - PR}" y2="${rnd(yScale(v))}"/>`);
    grid.push(`<text class="l-label" x="${PL - 6}" y="${rnd(yScale(v)) + 3}" text-anchor="end">${v === 0 ? "0" : v}</text>`);
  }

  const weeks = [];
  for (let w = 0; w < 4; w++) {
    const cx = rnd((xScale(w * 7) + xScale(w * 7 + 6)) / 2);
    const wkDate = addDays(start4w, w * 7);
    weeks.push(`<text class="l-week" x="${cx}" y="${H - 8}" text-anchor="middle">W${isoWeek(wkDate)}</text>`);
  }

  const dots = pts.filter(Boolean).map((p) => {
    const count = p.d.count || 1;
    const r = Math.min(6, 2.5 + Math.log2(count));
    return `<circle class="l-dot" cx="${rnd(p.x)}" cy="${rnd(p.y)}" r="${rnd(r)}"><title>${p.d.date} · ${count} plan${count === 1 ? "" : "s"} · avg ${p.d.avg_valence}</title></circle>`;
  }).join("");

  const labelled = pts.some(Boolean);
  if (!labelled) return '<p class="modal-empty">Not enough recent days yet.</p>';

  return `<svg class="lchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Mood valence over the last four weeks">
    <defs>
      <linearGradient id="lfill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#c4883a" stop-opacity="0.32"/>
        <stop offset="100%" stop-color="#c4883a" stop-opacity="0.02"/>
      </linearGradient>
    </defs>
    ${grid.join("")}
    <path class="l-area" d="${area}" fill="url(#lfill)" stroke="none"/>
    ${line ? `<path class="l-line" d="${line}"/>` : ""}
    ${dash ? `<path class="l-line l-dash" d="${dash}"/>` : ""}
    ${dots}
    ${weeks.join("")}
  </svg>`;
}

// --- weather panel ------------------------------------------------------------

function renderWeather(wx) {
  const wxRow = (label, data) => {
    const v = data && data.avg_valence;
    const n = (data && data.count) || 0;
    if (v == null) {
      return `<div class="wx-row"><span class="wx-label">${label}</span><span class="tiny">no entries yet</span></div>`;
    }
    const w = Math.min(47, Math.abs(v) * 47);
    const neg = v < 0;
    return `<div class="wx-row">
      <span class="wx-label">${label}</span>
      <div class="wx-track"><div class="wx-fill ${neg ? "neg" : "pos"}" style="left:${rnd2(neg ? 50 - w : 50)}%;width:${rnd2(w)}%"></div></div>
      <span class="wx-val">${v >= 0 ? "+" : ""}${v}</span>
      <span class="wx-n">${n}</span>
    </div>`;
  };
  const bands = ((wx && wx.by_temperature) || []).map((b) =>
    `<div class="wx-temp-row"><span>${esc(b.band)}</span><span><b>${b.avg_valence ?? "—"}</b> · ${b.count}</span></div>`
  ).join("");
  const r = wx && wx.temp_valence_r;
  return `
    <div>
      ${wxRow("Rainy", wx && wx.rainy)}
      ${wxRow("Clear", wx && wx.clear)}
      <div class="wx-legend"><span>−1</span><span>0</span><span>+1</span></div>
      <div class="wx-temp">
        ${bands}
        ${r != null ? `<div class="wx-temp-row"><span>Mood ↔ temp (r)</span><span><b>${r}</b></span></div>` : ""}
      </div>
    </div>`;
}

function rnd2(n) { return Math.round(n * 10) / 10; }

// --- calendar heatmap ---------------------------------------------------------

function renderHeatmap(hm) {
  const days = hm.days || [];
  const byDate = {};
  for (const d of days) if (d.date) byDate[d.date] = d;

  const start = parseDate(hm.start || fmtDate(new Date()));
  const end = parseDate(hm.end || start);
  const firstMonday = addDays(start, -((start.getUTCDay() + 6) % 7));
  const cols = Math.max(1, Math.ceil((dayDiff(firstMonday, end) + 1) / 7));
  const maxDate = String(hm.end);
  const minDate = String(hm.start);

  const cellFor = (dateStr, d) => {
    if (!d) return `<div class="hm-cell"></div>`;
    const fill = valenceFill(d.avg_valence);
    return `<div class="hm-cell" style="background:${fill}" title="${dateStr} · ${d.count} ${d.count === 1 ? "plan" : "plans"} · avg ${d.avg_valence}"></div>`;
  };

  const rowLabels = { 0: "Mon", 2: "Wed", 4: "Fri", 6: "Sun" };
  let cells = "";
  for (let r = 0; r < 7; r++) {
    cells += `<div class="hm-day-label">${rowLabels[r] || ""}</div>`;
    for (let c = 0; c < cols; c++) {
      const ds = fmtDate(addDays(firstMonday, c * 7 + r));
      const d = (ds >= minDate && ds <= maxDate && byDate[ds]) || null;
      cells += cellFor(ds, d);
    }
  }

  const colsDef = `34px repeat(${cols}, 13px)`;
  const legendCells = [-1, -0.5, 0, 0.5, 1].map((v) =>
    `<div class="hm-cell" style="background:${valenceFill(v)}"></div>`
  ).join("");

  return `
    <div class="hm-scroll">
      <div class="hm-grid" style="grid-template-columns:${colsDef}">
        ${buildMonthLabels(firstMonday, cols)}
        ${cells}
      </div>
      <div class="hm-legend">
        <span>−1</span>
        ${legendCells}
        <span>+1</span>
      </div>
    </div>`;
}

function buildMonthLabels(firstMonday, cols) {
  const parts = ['<div></div>'];  // spacer aligned with the weekday-label column
  let c = 0;
  while (c < cols) {
    const month = addDays(firstMonday, c * 7)
      .toLocaleString("en-US", { month: "short", timeZone: "UTC" });
    let n = 0;
    while (c + n < cols) {
      const next = addDays(firstMonday, (c + n) * 7)
        .toLocaleString("en-US", { month: "short", timeZone: "UTC" });
      if (next !== month) break;
      n++;
    }
    parts.push(`<div class="hm-month-label" style="grid-column: span ${n}">${month}</div>`);
    c += n;
  }
  return `<div class="hm-months" style="grid-template-columns:34px repeat(${cols}, 13px)">${parts.join("")}</div>`;
}
