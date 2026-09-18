// Send the same-origin CSRF token on every mutating API request.
(() => {
    const originalFetch = window.fetch.bind(window);
    const cookie = (name) => document.cookie.split(";").map(v => v.trim()).find(v => v.startsWith(`${name}=`))?.slice(name.length + 1) || "";
    window.fetch = (input, init = {}) => {
        const method = String(init.method || (input && input.method) || "GET").toUpperCase();
        if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
            const headers = new Headers(init.headers || {});
            const token = cookie("csrf_token");
            if (token) headers.set("X-CSRF-Token", token);
            init = { ...init, headers };
        }
        return originalFetch(input, init);
    };
})();

function t(key, vars) {
    if (window.DabotI18n && window.DabotI18n.t) return window.DabotI18n.t(key, vars);
    return key;
}

function tr(text, vars) {
    if (window.DabotI18n && window.DabotI18n.translateRaw) return window.DabotI18n.translateRaw(text, vars);
    return text;
}

const toast = (text, icon = "success") =>
    Swal.fire({ text: tr(text), icon, background: "#111a30", color: "#fff", confirmButtonColor: "#00ff88" });

let currentUser = null;
let currentGuildId = null;
let permissionsConfig = { is_admin: false, permissions: [], scopes: {} };
let serverChannels = [];
let serverConfigData = {};
let guildsCache = {};
let userCache = {};

const PREMIUM_PAGE = "/premium";

function premiumAction(guild) {
    if (guild.is_premium) return "";
    return `<a class="btn btn-primary btn-block btn-sm" href="${PREMIUM_PAGE}?guild=${encodeURIComponent(guild.id)}">${t("dash.get_premium")}</a>`;
}

function $(id) { return document.getElementById(id); }
function setText(id, text) { const el = $(id); if (el) el.innerText = text; }
function showLoading() { const el = $("loading-overlay"); if (el) el.classList.remove("hidden"); }
function hideLoading() { const el = $("loading-overlay"); if (el) el.classList.add("hidden"); }
function closeSidebar() { const el = $("sidebar"); if (el) el.classList.remove("open"); }

function iconHtml(guild) {
    if (guild.icon) {
        return `<img src="https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png" alt="">`;
    }
    const initials = (guild.name || "?").split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase();
    return `<div class="server-fallback">${initials}</div>`;
}

function rolePills(g) {
    let html = "";
    if (g.via_bot) html += `<span class="pill owner">${t("pill.creator")}</span>`;
    else if (g.user_role === "owner") html += `<span class="pill owner">${t("pill.owner")}</span>`;
    else if (g.user_role === "gestor") html += `<span class="pill">${t("pill.staff")}</span>`;
    if (g.is_premium) html += `<span class="pill vip">${t("dash.premium")}</span>`;
    return html;
}

async function loadUser() {
    try {
        const userRes = await fetch("/api/user/me", { cache: "no-store" });
        if (userRes.status === 401) {
            window.location.href = "/login";
            return;
        }
        currentUser = await userRes.json();
        setText("me-name", currentUser.username || "Usuario");
        const av = $("me-avatar");
        if (av && currentUser.avatar) {
            av.src = `https://cdn.discordapp.com/avatars/${currentUser.user_id}/${currentUser.avatar}.png`;
        }
        if (currentUser.is_owner) {
            setText("me-role", "Owner");
            const navAdmin = $("nav-admin");
            if (navAdmin) navAdmin.classList.remove("hidden");
        }
    } catch (e) {
        console.error(e);
        ["active-servers-grid", "invitable-servers-grid", "regular-servers-grid"].forEach(id => {
            const g = $(id);
            if (g) g.innerHTML = `<div class="empty">${t("dash.empty.session")}</div>`;
        });
    }
    await loadGuildsList();
    refreshBotStatus();
    setInterval(refreshBotStatus, 12000);
    setInterval(pollActiveTabRealtime, 15000);
    try {
        const qs = new URLSearchParams(location.search);
        const g = qs.get("guild");
        const ticket = qs.get("ticket");
        if (g) {
            await selectGuild(String(g));
            if (ticket) {
                switchTab("tickets");
                await openTicket(ticket);
            }
        }
    } catch (e) { console.error(e); }
}

async function refreshBotStatus() {
    try {
        const s = await (await fetch("/api/status?_=" + Date.now(), { cache: "no-store" })).json();
        const el = document.getElementById("bot-status");
        const ping = (s.latency_ms != null && s.latency_ms !== "") ? `${s.latency_ms} ms` : "—";
        const guilds = s.guilds != null ? s.guilds : "—";
        const users = s.users != null ? s.users : "—";
        if (s.online) {
            el.innerHTML = `<span class="dot on"></span> ${s.username || "Dabot"} · ${ping} · ${guilds} ${t("dash.servers")} · ${users} users`;
        } else if (s.latency_ms != null) {
            el.innerHTML = `<span class="dot"></span> ${s.username || "Dabot"} · ${ping} · ${guilds} ${t("dash.servers")} · ${t("dash.bot_offline")}`;
        } else {
            el.innerHTML = `<span class="dot"></span> ${t("dash.bot_offline")}`;
        }
    } catch {
        document.getElementById("bot-status").innerHTML = `<span class="dot"></span> ${t("dash.no_heartbeat")}`;
    }
}

async function pollActiveTabRealtime() {
    if (document.hidden) return;
    if (!currentGuildId) return;
    try {
        const activeTabEl = document.querySelector(".tab-content:not(.hidden)");
        if (!activeTabEl) return;
        const tabId = activeTabEl.id.replace("tab-", "");

        // Avoid disrupting user typing
        const activeTag = document.activeElement ? document.activeElement.tagName : "";
        if (activeTag === "INPUT" || activeTag === "TEXTAREA" || activeTag === "SELECT") {
            return;
        }

        if (tabId === "tickets") {
            const box = $("ticket-thread");
            if (box && !box.classList.contains("hidden") && box.dataset.ticketId) {
                await openTicket(box.dataset.ticketId, true);
            }
            loadTickets();
        } else if (tabId === "overview") {
            const ov = await (await fetch(`/api/guilds/${currentGuildId}/overview`)).json();
            if ($("ov-members")) $("ov-members").innerText = ov.members ?? "—";
            if ($("ov-levels")) $("ov-levels").innerText = ov.level_records ?? "—";
            if ($("ov-infra")) $("ov-infra").innerText = ov.infractions ?? "—";
            if ($("ov-invites")) $("ov-invites").innerText = ov.invites ?? "—";
            if ($("ov-verifies")) $("ov-verifies").innerText = ov.verifications ?? "—";
        } else if (tabId === "verifications") {
            loadVerifications();
        } else if (tabId === "alts") {
            loadAlts();
        }
    } catch (e) {
        // silent
    }
}

async function loadGuildsList() {
    const paintError = (msg) => {
        ["active-servers-grid", "invitable-servers-grid", "regular-servers-grid"].forEach(id => {
            const g = $(id);
            if (g) g.innerHTML = `<div class="empty" style="grid-column:1/-1">${msg}</div>`;
        });
    };
    try {
        const res = await fetch("/api/user/guilds", { cache: "no-store" });
        if (res.status === 401) {
            window.location.href = "/login";
            return;
        }
        const data = await res.json();
        if (!res.ok) {
            paintError(data.detail || t("dash.network"));
            return;
        }
        guildsCache = {};
        const paint = (list, gridId, mode) => {
            const grid = $(gridId);
            if (!grid) return;
            grid.innerHTML = "";
            if (!list.length) {
                grid.innerHTML = `<div class="empty" style="grid-column:1/-1">${t("dash.empty")}</div>`;
                return;
            }
            list.forEach(g => {
                guildsCache[g.id] = g;
                const card = document.createElement("div");
                card.className = "server-card glass";
                card.dataset.name = (g.name || "").toLowerCase();
                let action = "";
                if (mode === "active") {
                    action = `<button class="btn btn-primary btn-block btn-sm" onclick="selectGuild('${g.id}')"><i class="fas fa-sliders"></i> ${t("dash.configure")}</button>`;
                } else if (mode === "invite") {
                    const url = g.invite_url || `https://discord.com/oauth2/authorize?client_id=${g.client_id}&permissions=2186104270071&scope=bot%20applications.commands&guild_id=${g.id}`;
                    action = `<a class="btn btn-discord btn-block btn-sm" href="${url}" target="_blank"><i class="fab fa-discord"></i> ${t("dash.invite")}</a>`;
                } else {
                    action = `<button class="btn btn-ghost btn-block btn-sm" onclick="selectGuild('${g.id}')"><i class="fas fa-eye"></i> ${t("dash.sanctions")}</button>`;
                }
                const safeName = (g.name || "").replace(/</g, "");
                const membersHtml = g.approximate_member_count ? `<span class="mono" style="font-size:11.5px;color:var(--muted);display:inline-flex;align-items:center;gap:4px;"><i class="fas fa-users" style="color:var(--green);font-size:11px"></i> ${g.approximate_member_count.toLocaleString()} miembros</span>` : "";
                card.innerHTML = `
                    ${iconHtml(g)}
                    <h3 title="${safeName}">${safeName}</h3>
                    ${membersHtml}
                    <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin:2px 0 4px">${rolePills(g)}</div>
                    <div style="width:100%;margin-top:auto;display:flex;flex-direction:column;gap:8px">${action}${premiumAction(g)}</div>
                `;
                grid.appendChild(card);
            });
        };
        paint(data.active_admin || [], "active-servers-grid", "active");
        paint(data.invitable || [], "invitable-servers-grid", "invite");
        paint(data.regular_member || [], "regular-servers-grid", "member");
    } catch (e) {
        console.error(e);
        paintError(t("dash.network"));
    }
}

function filterServers(q) {
    q = (q || "").toLowerCase();
    document.querySelectorAll(".server-card").forEach(c => {
        c.style.display = !q || (c.dataset.name || "").includes(q) ? "" : "none";
    });
}

function showServers() {
    if (typeof stopLivePoll === "function") stopLivePoll();
    closeSidebar();
    document.getElementById("view-servers").classList.remove("hidden");
    document.getElementById("view-admin").classList.add("hidden");
    document.getElementById("view-guild").classList.add("hidden");
    const vs = document.getElementById("view-suggest");
    if (vs) vs.classList.add("hidden");
    document.getElementById("guild-nav").classList.add("hidden");
    document.getElementById("top-title").innerText = t("dash.your_servers");
    document.getElementById("top-sub").innerText = "dabot.davito.es";
    loadGuildsList();
}

function showSuggest() {
    closeSidebar();
    document.getElementById("view-servers").classList.add("hidden");
    document.getElementById("view-admin").classList.add("hidden");
    document.getElementById("view-guild").classList.add("hidden");
    document.getElementById("guild-nav").classList.add("hidden");
    const vs = document.getElementById("view-suggest");
    if (vs) vs.classList.remove("hidden");
    document.getElementById("top-title").innerText = "Sugerir a Dabot";
    document.getElementById("top-sub").innerText = "Owners y administradores";
    const sel = $("suggest-guild");
    if (!sel) return;
    const admins = Object.values(guildsCache).filter(g =>
        g && (g.user_role === "owner" || g.user_role === "gestor" || g.is_owner || currentUser && currentUser.is_owner)
    );
    sel.innerHTML = admins.length
        ? admins.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join("")
        : `<option value="">No hay servidores donde seas admin</option>`;
    if (currentGuildId && [...sel.options].some(o => o.value === String(currentGuildId))) {
        sel.value = String(currentGuildId);
    }
}

async function submitBotSuggestion() {
    const text = ($("suggest-text") && $("suggest-text").value || "").trim();
    const guildId = $("suggest-guild") && $("suggest-guild").value;
    if (text.length < 8) return toast("Escribe un poco más (mínimo 8 caracteres).", "warning");
    try {
        const res = await fetch("/api/dabot/suggestions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text, guild_id: guildId || null })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Error");
        if ($("suggest-text")) $("suggest-text").value = "";
        toast(data.posted ? `Enviada (#${data.id}). Te avisaremos por MD.` : `Guardada (#${data.id}), pero no se publicó en Discord.`);
    } catch (e) {
        toast(e.message || "No se pudo enviar", "error");
    }
}

function showGlobalAdmin() {
    closeSidebar();
    document.getElementById("view-servers").classList.add("hidden");
    document.getElementById("view-guild").classList.add("hidden");
    const vsA = document.getElementById("view-suggest");
    if (vsA) vsA.classList.add("hidden");
    document.getElementById("view-admin").classList.remove("hidden");
    document.getElementById("guild-nav").classList.add("hidden");
    document.getElementById("top-title").innerText = t("dash.admin");
    document.getElementById("top-sub").innerText = t("dash.control_all");
    loadAdminDiagnostics();
    loadAdminBotGuilds();
    loadAdminAnnouncements();
    loadAdminAlts();
    loadAdminVerifications();
    loadAdminPrivacyRequests();
    loadAdminLiveLogs();
    toggleLiveLogsAuto(true);
}

async function selectGuild(guildId, fallback) {
    if (typeof stopLivePoll === "function") stopLivePoll();
    toggleLiveLogsAuto(false);
    const g = guildsCache[guildId] || fallback;
    if (!g) return;
    guildsCache[guildId] = g;
    currentGuildId = guildId;
    ticketDesignerReady = false;
    closeSidebar();
    document.getElementById("view-servers").classList.add("hidden");
    document.getElementById("view-admin").classList.add("hidden");
    const vsG = document.getElementById("view-suggest");
    if (vsG) vsG.classList.add("hidden");
    document.getElementById("view-guild").classList.remove("hidden");
    document.getElementById("guild-nav").classList.remove("hidden");
    document.getElementById("top-title").innerText = g.name;
    document.getElementById("top-sub").innerText = g.is_premium ? t("dash.premium") : t("dash.top.server");

    const sName = document.getElementById("sidebar-guild-name");
    const sIcon = document.getElementById("sidebar-guild-icon");
    if (sName) sName.innerText = g.name || "Servidor";
    if (sIcon) {
        if (g.icon) {
            sIcon.src = `https://cdn.discordapp.com/icons/${g.id}/${g.icon}.png?size=64`;
        } else {
            sIcon.src = "https://cdn.discordapp.com/embed/avatars/0.png";
        }
    }

    const accRes = await fetch(`/api/guilds/${guildId}/permissions`);
    permissionsConfig = await accRes.json();
    const configBtn = document.getElementById("nav-config");
    const staffBtn = document.getElementById("nav-staff");
    if (permissionsConfig.is_admin || permissionsConfig.permissions.includes("manage_config")) {
        configBtn.classList.remove("hidden");
    } else {
        configBtn.classList.add("hidden");
    }
    staffBtn.classList.toggle("hidden", !permissionsConfig.is_admin);

    if (permissionsConfig.is_admin || permissionsConfig.permissions.includes("manage_config")) {
        try {
            const [chansRes, rolesRes] = await Promise.all([
                fetch(`/api/guilds/${guildId}/channels`),
                fetch(`/api/guilds/${guildId}/roles`)
            ]);
            serverChannels = await chansRes.json();
            window._roles = await rolesRes.json();
            populateChannelDropdowns();
            populateRoleDropdowns(window._roles);
        } catch (e) {
            console.error(e);
        }
    }

    if (permissionsConfig.is_admin || permissionsConfig.permissions.includes("manage_config")) {
        switchTab("overview");
    } else {
        switchTab("ranking");
    }
}

function switchTab(tabId) {
    closeSidebar();
    document.querySelectorAll(".tab-content").forEach(tab => tab.classList.add("hidden"));
    const activeTab = document.getElementById(`tab-${tabId}`);
    if (activeTab) activeTab.classList.remove("hidden");
    document.querySelectorAll("#guild-nav .nav-btn").forEach(btn => btn.classList.remove("active"));
    const matchedBtn = document.getElementById(`nav-${tabId}`);
    if (matchedBtn) matchedBtn.classList.add("active");
    loadGuildData(currentGuildId, tabId);
}

function switchSubConfig(subId) {
    document.querySelectorAll(".sub-config-content").forEach(el => el.classList.add("hidden"));
    document.querySelectorAll(".mod-nav button").forEach(el => el.classList.remove("active"));
    const targetContent = document.getElementById(`sub-config-${subId}`);
    if (targetContent) targetContent.classList.remove("hidden");
    const targetBtn = document.getElementById(`sub-nav-${subId}`);
    if (targetBtn) targetBtn.classList.add("active");
}

function populateChannelDropdowns() {
    const ids = [
        "cfg-lvl-channel", "cfg-lead-channel", "cfg-log-messages", "cfg-log-moderation",
        "cfg-log-voice", "cfg-log-members", "cfg-log-joins", "cfg-log-alts", "cfg-log-hijack", "cfg-log-tickets", "cfg-log-verification", "cfg-ticket-transcript", "tp-publish-channel",
        "staff-channels-select", "cfg-welcome-channel", "cfg-goodbye-channel",
        "cfg-star-channel", "cfg-raid-channel", "action-ticket-channel", "action-verify-channel",
        "cfg-nuke-channel", "cfg-suggestions-channel", "cfg-mod-appeals-channel"
    ];
    ids.forEach(id => {
        const select = document.getElementById(id);
        if (!select) return;
        const isMulti = select.hasAttribute("multiple");
        select.innerHTML = isMulti ? "" : `<option value="">${t("dash.empty.disabled")}</option>`;
        (serverChannels || []).forEach(c => {
            if (c.type === 0 || c.type === 5 || (isMulti && c.type === 4)) {
                const opt = document.createElement("option");
                opt.value = c.id;
                opt.innerText = c.type === 4 ? `📂 ${c.name}` : `#${c.name}`;
                select.appendChild(opt);
            }
        });
    });
}

function populateRoleDropdowns(roles) {
    const roleSelects = ["cfg-mod-mute-role"];
    roleSelects.forEach(id => {
        const select = document.getElementById(id);
        if (!select) return;
        select.innerHTML = `<option value="">${t("dash.empty.disabled")}</option>`;
        (roles || []).forEach(r => {
            const opt = document.createElement("option");
            opt.value = r.id;
            opt.innerText = `@${r.name}`;
            select.appendChild(opt);
        });
    });
}

async function resolveUsers(ids) {
    const missing = [...new Set(ids.map(String))].filter(id => id && !userCache[id]);
    if (!missing.length) return userCache;
    try {
        const res = await fetch("/api/users/resolve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ids: missing })
        });
        const data = await res.json();
        Object.assign(userCache, data.users || {});
    } catch (e) {
        console.error(e);
    }
    return userCache;
}

function userCell(id) {
    const u = userCache[String(id)];
    if (!u) return `<span class="mono">${esc(id)}</span>`;
    const name = u.global_name || u.username || id;
    return `<div class="user-cell"><img src="${esc(u.avatar_url || "")}" alt=""><span>${esc(name)}</span></div>`;
}

async function loadGuildData(guildId, tabId) {
    if (!guildId) return;

    if (tabId === "discord") {
        loadDiscord();
    }
    if (tabId === "logs") {
        loadAudit();
    }
    if (tabId === "templates") {
        loadTemplates();
    }
    if (tabId === "overview") {
        try {
            const ov = await (await fetch(`/api/guilds/${guildId}/overview`)).json();
            document.getElementById("ov-members").innerText = ov.members ?? "—";
            document.getElementById("ov-levels").innerText = ov.level_records ?? "—";
            document.getElementById("ov-infra").innerText = ov.infractions ?? "—";
            document.getElementById("ov-invites").innerText = ov.invites ?? "—";
            if ($("ov-verifies")) document.getElementById("ov-verifies").innerText = ov.verifications ?? "—";
            renderHealth(ov.health, ov.premium, ov.is_premium);
        } catch (e) {
            console.error(e);
        }
    }
    if (tabId === "tickets") {
        loadTickets();
        ensureTicketDesigner();
    }

    if (tabId === "config" && (permissionsConfig.is_admin || permissionsConfig.permissions.includes("manage_config"))) {
        try {
            const configRes = await fetch(`/api/guilds/${guildId}/config`);
            serverConfigData = await configRes.json();
            document.getElementById("cfg-prefix").value = serverConfigData.prefix || "!";
            let langVal = serverConfigData.lang || serverConfigData.language || "es-ES";
            if (langVal === "es") langVal = "es-ES";
            if (langVal === "en") langVal = "en-US";
            document.getElementById("cfg-lang").value = langVal;

            const lvl = serverConfigData.leveling || {};
            document.getElementById("cfg-leveling-enabled").checked = lvl.enabled === true;
            const minXp = (o, d) => (o && typeof o === "object" ? o.min : (typeof o === "number" ? o : d));
            const maxXp = (o, d) => (o && typeof o === "object" ? o.max : (typeof o === "number" ? o : d));
            document.getElementById("cfg-tx-min").value = minXp(lvl.text_xp, 15);
            document.getElementById("cfg-tx-max").value = maxXp(lvl.text_xp, 25);
            document.getElementById("cfg-vx-min").value = minXp(lvl.voice_xp, 10);
            document.getElementById("cfg-vx-max").value = maxXp(lvl.voice_xp, 20);
            document.getElementById("cfg-lvl-channel").value = lvl.level_up_channel || "";
            document.getElementById("cfg-lead-channel").value = lvl.leaderboard_channel || "";
            document.getElementById("cfg-level-card-custom").value = lvl.card_custom_text || "";
            const levelLayout = lvl.card_layout || {};
            const levelLayoutDefaults = {
                avatar_x: 158, avatar_y: 200, avatar_size: 220,
                name_x: 310, name_y: 48, rank_x: 310, rank_y: 118,
                level_x: 1152, level_y: 40, bar_x: 310, bar_y: 250,
                bar_width: 830, bar_height: 44, custom_x: 720, custom_y: 345, custom_size: 28
            };
            Object.keys(levelLayoutDefaults).forEach(key => {
                const el = document.getElementById(`cfg-level-${key.replaceAll("_", "-")}`);
                if (el) el.value = levelLayout[key] ?? levelLayoutDefaults[key];
            });
            const persona = serverConfigData.premium_persona || {};
            if ($("cfg-premium-bot-name")) $("cfg-premium-bot-name").value = persona.name || "";
            if ($("cfg-premium-bot-avatar")) $("cfg-premium-bot-avatar").value = persona.avatar || "";

            const chatbot = serverConfigData.chatbot || {};
            if ($("cfg-ai-enabled")) $("cfg-ai-enabled").checked = chatbot.enabled === true;
            document.getElementById("cfg-ai-prompt").value = chatbot.personality_prompt || "";
            document.getElementById("cfg-ai-toxicity").value = chatbot.toxicity_threshold || 0.8;
            document.getElementById("toxicity-value").innerText = chatbot.toxicity_threshold || 0.8;
            if ($("cfg-ai-channels")) $("cfg-ai-channels").value = (chatbot.channel_ids || []).join(", ");
            if ($("cfg-achievements-enabled")) $("cfg-achievements-enabled").checked = (serverConfigData.achievements || {}).enabled === true;

            const logs = serverConfigData.logs || {};
            const tickets = serverConfigData.tickets || {};
            document.getElementById("cfg-log-messages").value = logs.messages || "";
            document.getElementById("cfg-log-moderation").value = logs.moderation || "";
            document.getElementById("cfg-log-voice").value = logs.voice || "";
            document.getElementById("cfg-log-members").value = logs.members || "";
            document.getElementById("cfg-log-joins").value = logs.joins || "";
            if ($("cfg-log-alts")) document.getElementById("cfg-log-alts").value = logs.alts || "";
            if ($("cfg-log-hijack")) $("cfg-log-hijack").value = logs.hijack || "";
            if ($("cfg-log-tickets")) $("cfg-log-tickets").value = logs.tickets || tickets.transcript_channel_id || "";
            if ($("cfg-log-verification")) $("cfg-log-verification").value = logs.verification || "";

            document.getElementById("cfg-ticket-category").value = tickets.category_name || "Tickets";
            document.getElementById("cfg-ticket-transcript").value = tickets.transcript_channel_id || logs.tickets || "";
            fillTicketDesigner(tickets);

            const mod = serverConfigData.moderation || {};
            const esc = mod.escalate || {};
            if ($("cfg-esc-enabled")) $("cfg-esc-enabled").checked = !!esc.enabled;
            if ($("cfg-esc-to")) $("cfg-esc-to").value = esc.warns_timeout || 3;
            if ($("cfg-esc-mins")) $("cfg-esc-mins").value = esc.timeout_minutes || 30;
            if ($("cfg-esc-kick")) $("cfg-esc-kick").value = esc.warns_kick || 5;
            if ($("cfg-esc-window")) $("cfg-esc-window").value = esc.window_hours || 24;
            if ($("cfg-mod-appeals-channel")) $("cfg-mod-appeals-channel").value = mod.appeals_channel || "";
            if ($("cfg-mod-mute-role")) $("cfg-mod-mute-role").value = mod.mute_role_id || "";
            loadConfigRevisions();

            const am = serverConfigData.automod || {};
            document.getElementById("cfg-automod-enabled").checked = !!am.enabled;
            document.getElementById("cfg-automod-block-invites").checked = am.block_invites !== false;
            document.getElementById("cfg-automod-auto-warn").checked = am.auto_warn === true;
            if ($("cfg-automod-hijack")) $("cfg-automod-hijack").checked = am.hijack !== false;
            if ($("cfg-automod-hijack-timeout")) $("cfg-automod-hijack-timeout").checked = am.hijack_timeout !== false;
            document.getElementById("cfg-automod-mentions").value = am.mention_limit || 5;
            document.getElementById("cfg-automod-spam-threshold").value = am.spam_threshold || 3;
            fillLinksConfig(am.links || {});

            const w = serverConfigData.welcome || {};
            document.getElementById("cfg-welcome-enabled").checked = !!w.enabled;
            document.getElementById("cfg-welcome-channel").value = w.channel_id || "";
            document.getElementById("cfg-welcome-msg").value = w.message || "";
            document.getElementById("cfg-welcome-heading").value = w.card_heading || ((serverConfigData.lang || "").startsWith("en") ? "WELCOME" : "BIENVENIDO");
            document.getElementById("cfg-welcome-member-label").value = w.member_label || ((serverConfigData.lang || "").startsWith("en") ? "Member" : "Miembro");
            document.getElementById("cfg-welcome-custom-text").value = w.custom_text || "";
            const wl = w.layout || {};
            const layoutDefaults = {avatar_x:512, avatar_y:205, avatar_size:220, heading_x:512, heading_y:330, name_x:512, name_y:391, member_x:512, member_y:435, custom_x:512, custom_y:60, custom_size:26};
            Object.keys(layoutDefaults).forEach(key => {
                const el = document.getElementById(`cfg-welcome-${key.replaceAll("_", "-")}`);
                if (el) el.value = wl[key] ?? layoutDefaults[key];
            });
            const gb = serverConfigData.goodbye || {};
            document.getElementById("cfg-goodbye-enabled").checked = !!gb.enabled;
            document.getElementById("cfg-goodbye-channel").value = gb.channel_id || "";
            document.getElementById("cfg-goodbye-msg").value = gb.message || "";

            const star = serverConfigData.starboard || {};
            document.getElementById("cfg-star-enabled").checked = !!star.enabled;
            document.getElementById("cfg-star-channel").value = star.channel_id || "";
            document.getElementById("cfg-star-limit").value = star.limit || 3;

            const eco = serverConfigData.economy || {};
            document.getElementById("cfg-eco-enabled").checked = eco.enabled !== false;
            document.getElementById("cfg-eco-symbol").value = eco.currency_symbol || "🦞";

            try {
                const raid = await (await fetch(`/api/guilds/${guildId}/antiraid`)).json();
                document.getElementById("cfg-raid-enabled").checked = !!raid.enabled;
                document.getElementById("cfg-raid-threshold").value = raid.join_threshold || 10;
                document.getElementById("cfg-raid-window").value = raid.window_seconds || 10;
                document.getElementById("cfg-raid-lock").value = raid.lockdown_minutes || 5;
                document.getElementById("cfg-raid-channel").value = raid.alert_channel_id || "";
            } catch (e) { console.error(e); }

            const sugg = serverConfigData.suggestions || {};
            if ($("cfg-suggestions-channel")) $("cfg-suggestions-channel").value = sugg.channel || "";
            if ($("cfg-suggestions-threshold")) $("cfg-suggestions-threshold").value = sugg.auto_approve_threshold || 10;

            try {
                const nukeData = await (await fetch(`/api/guilds/${guildId}/antinuke`)).json();
                const nuke = nukeData.config || {};
                if ($("cfg-nuke-enabled")) $("cfg-nuke-enabled").checked = !!nuke.enabled;
                if ($("cfg-nuke-action")) $("cfg-nuke-action").value = nuke.action || "strip_roles";
                if ($("cfg-nuke-channel")) $("cfg-nuke-channel").value = nuke.log_channel_id || "";
                if ($("cfg-nuke-channels")) $("cfg-nuke-channels").value = nuke.max_channel_deletes || 3;
                if ($("cfg-nuke-roles")) $("cfg-nuke-roles").value = nuke.max_role_deletes || 3;
                if ($("cfg-nuke-kicks")) $("cfg-nuke-kicks").value = nuke.max_kicks || 5;
                if ($("cfg-nuke-bans")) $("cfg-nuke-bans").value = nuke.max_bans || 5;
                if ($("cfg-nuke-window")) $("cfg-nuke-window").value = nuke.window_seconds || 10;
                renderAntiNukeLogs(nukeData.logs || []);
            } catch (e) { console.error(e); }

            loadAutoResponses();
            loadCustomCommands();

            loadGuildBackupInfo();
            switchSubConfig("general");
        } catch (e) {
            console.error(e);
        }
    }

    if (tabId === "moderation") {
        loadInfractionsAndAppeals();
        loadModQueue();
        const exp = document.getElementById("btn-export-infra");
        if (exp) exp.href = `/api/guilds/${guildId}/infractions.csv`;
    }
    if (tabId === "alts") loadAlts();
    if (tabId === "verifications") loadVerifications();

    if (tabId === "staff" && permissionsConfig.is_admin) {
        try {
            const roles = await (await fetch(`/api/guilds/${guildId}/roles`)).json();
            const rSelect = document.getElementById("staff-role-select");
            rSelect.innerHTML = `<option value="">${t("dash.empty.select_role")}</option>`;
            roles.forEach(r => {
                const opt = document.createElement("option");
                opt.value = r.id;
                opt.innerText = r.name;
                rSelect.appendChild(opt);
            });
            document.getElementById("staff-scope-type").onchange = (e) => {
                document.getElementById("staff-channels-container").classList.toggle("hidden", e.target.value === "global");
            };
        } catch (e) { console.error(e); }
    }

    if (tabId === "ranking") {
        try {
            const rankData = await (await fetch(`/api/guilds/${guildId}/leaderboard`)).json();
            await resolveUsers((rankData.leaderboard || []).map(u => u.user_id));
            const tbody = document.getElementById("ranking-table-body");
            tbody.innerHTML = "";
            if (!rankData.leaderboard.length) {
                tbody.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.xp")}</td></tr>`;
            } else {
                rankData.leaderboard.forEach((u, i) => {
                    tbody.insertAdjacentHTML("beforeend", `<tr>
                        <td>#${i + 1}</td><td>${userCell(u.user_id)}</td>
                        <td>${u.level}</td><td>${u.xp}</td><td>${u.weekly_xp}</td></tr>`);
                });
            }
        } catch (e) { console.error(e); }
    }

    if (tabId === "invites") {
        const btnInvite = document.getElementById("btn-admin-create-invite");
        if (btnInvite) {
            btnInvite.classList.toggle("hidden", !(currentUser && currentUser.is_owner));
        }
        try {
            const invData = await (await fetch(`/api/guilds/${guildId}/invites`)).json();
            await resolveUsers((invData.leaderboard || []).map(u => u.inviter_id));
            const tbody = document.getElementById("invites-table-body");
            tbody.innerHTML = "";
            if (!invData.leaderboard.length) {
                tbody.innerHTML = `<tr><td colspan="2" class="empty">${t("dash.empty.invites")}</td></tr>`;
            } else {
                invData.leaderboard.forEach(u => {
                    tbody.insertAdjacentHTML("beforeend", `<tr>
                        <td>${userCell(u.inviter_id)}</td><td>${u.invite_count}</td></tr>`);
                });
            }
        } catch (e) { console.error(e); }
    }

    if (tabId === "economy") {
        try {
            const data = await (await fetch(`/api/guilds/${guildId}/economy`)).json();
            await resolveUsers((data.ranking || []).map(u => u.user_id));
            const body = document.getElementById("economy-table-body");
            body.innerHTML = "";
            if (!data.ranking.length) {
                body.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.economy")}</td></tr>`;
            } else {
                data.ranking.forEach((u, i) => {
                    body.insertAdjacentHTML("beforeend", `<tr><td>#${i + 1}</td><td>${userCell(u.user_id)}</td><td>${u.balance}</td><td>${u.bank}</td><td><b>${u.total}</b></td></tr>`);
                });
            }
            const shop = document.getElementById("economy-shop-body");
            shop.innerHTML = data.shop?.length ? data.shop.map(i => `<tr><td>${esc(i.item_name)}</td><td>${esc(i.price)}</td><td>${esc(i.description || "—")}</td></tr>`).join("") : `<tr><td colspan="3" class="empty">${t("dash.economy.empty")}</td></tr>`;
        } catch (e) { console.error(e); }
    }
}

async function saveStaffPermissions() {
    const roleId = document.getElementById("staff-role-select").value;
    if (!roleId) return toast(t("toast.select_role"), "warning");
    const permissions = [...document.querySelectorAll(".staff-perm-checkbox:checked")].map(c => c.value);
    const scopeType = document.getElementById("staff-scope-type").value;
    const scopedChannels = [];
    if (scopeType !== "global") {
        for (const opt of document.getElementById("staff-channels-select").options) {
            if (opt.selected) scopedChannels.push(opt.value);
        }
    }
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/staff-permissions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ role_id: parseInt(roleId), permissions, scope_type: scopeType, scoped_channels: scopedChannels })
        });
        if (res.ok) toast("Permisos guardados");
        else throw new Error();
    } catch {
        toast("Error al guardar staff", "error");
    }
}

async function loadInfractionsAndAppeals() {
    try {
        const infractions = await (await fetch(`/api/guilds/${currentGuildId}/infractions`)).json();
        await resolveUsers(infractions.map(i => i.user_id));
        const tbody = document.getElementById("infractions-table-body");
        tbody.innerHTML = "";
        if (!infractions.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty">${t("dash.empty.infractions")}</td></tr>`;
        } else {
            infractions.forEach(i => {
                const canAppeal = String(i.user_id) === String(currentUser.user_id) && i.status === "active";
                const appealBtn = canAppeal
                    ? `<button class="btn btn-ghost btn-sm" onclick="openAppealModal(${i.id})">Apelar</button>`
                    : `<span class="pill">${i.status || "active"}</span>`;
                tbody.insertAdjacentHTML("beforeend", `<tr>
                    <td>${userCell(i.user_id)}</td>
                    <td><span class="pill">${i.type}</span></td>
                    <td>${esc(i.reason || "")}</td>
                    <td>${esc(i.staff_note || "—")}</td>
                    <td>${new Date(i.timestamp).toLocaleString()}</td>
                    <td>${appealBtn}</td></tr>`);
            });
        }
    } catch (e) { console.error(e); }

    const isStaff = permissionsConfig.is_admin || permissionsConfig.permissions.includes("resolve_appeals");
    const appealsSection = document.getElementById("appeals-section");
    if (!appealsSection) return;
    if (!isStaff) { appealsSection.classList.add("hidden"); return; }
    appealsSection.classList.remove("hidden");
    try {
        const appeals = await (await fetch(`/api/guilds/${currentGuildId}/appeals`)).json();
        await resolveUsers(appeals.map(a => a.user_id));
        const tbody = document.getElementById("appeals-table-body");
        tbody.innerHTML = "";
        if (!appeals.length) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.appeals")}</td></tr>`;
        } else {
            appeals.forEach(a => {
                const actBtn = a.status === "pending"
                    ? `<button class="btn btn-primary btn-sm" onclick="resolveAppeal(${a.infraction_id}, 'approve')">Aceptar</button>
                       <button class="btn btn-danger btn-sm" onclick="resolveAppeal(${a.infraction_id}, 'reject')">Rechazar</button>`
                    : `<span class="pill">${a.status}</span>`;
                tbody.insertAdjacentHTML("beforeend", `<tr>
                    <td class="mono">#${a.infraction_id}</td>
                    <td>${userCell(a.user_id)}</td>
                    <td>${a.appeal_reason || ""}</td>
                    <td>${a.status}</td><td>${actBtn}</td></tr>`);
            });
        }
    } catch (e) { console.error(e); }
}

async function openApplySanctionModal() {
    const { value: formValues } = await Swal.fire({
        title: t("dash.raw.apply_sanction"),
        background: "#111a30", color: "#fff", confirmButtonColor: "#fb7185",
        confirmButtonText: t("dash.sanction"),
        html: `<div class="stack" style="text-align:left">
            <label>${t("dash.user_id_label")}</label><input id="swal-user-id" class="swal2-input">
            <select id="swal-type" class="swal2-select">
                <option value="warn">Warn</option>
                <option value="timeout">Timeout 10m</option>
                <option value="kick">Kick</option>
                <option value="ban">Ban</option>
            </select>
            <textarea id="swal-reason" class="swal2-textarea" placeholder="${t("dash.table.reason")}"></textarea>
        </div>`,
        preConfirm: () => ({
            user_id: document.getElementById("swal-user-id").value,
            type: document.getElementById("swal-type").value,
            reason: document.getElementById("swal-reason").value
        })
    });
    if (!formValues) return;
    if (!formValues.user_id || !formValues.reason) return toast(t("dash.required_fields"), "warning");
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/infractions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: parseInt(formValues.user_id), type: formValues.type, reason: formValues.reason })
        });
        if (res.ok) { toast(t("toast.applied")); loadInfractionsAndAppeals(); }
        else {
            const data = await res.json();
            throw new Error(data.detail);
        }
    } catch (e) { toast(e.message || "Error", "error"); }
}

async function openAppealModal(infractionId) {
    const { value: text } = await Swal.fire({
        title: `Apelar #${infractionId}`, input: "textarea",
        showCancelButton: true, background: "#111a30", color: "#fff", confirmButtonColor: "#00ff88"
    });
    if (!text) return;
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/appeals`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ infraction_id: infractionId, reason: text })
        });
        if (res.ok) { toast(t("toast.appeal_sent")); loadInfractionsAndAppeals(); }
        else { const data = await res.json(); throw new Error(data.detail); }
    } catch (e) { toast(e.message || "Error", "error"); }
}

async function resolveAppeal(infractionId, action) {
    const { value: responseText } = await Swal.fire({
        title: action === "approve" ? "Aprobar" : "Rechazar",
        input: "textarea", showCancelButton: true,
        background: "#111a30", color: "#fff",
        confirmButtonColor: action === "approve" ? "#00ff88" : "#fb7185"
    });
    if (responseText === undefined) return;
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/appeals/${infractionId}/resolve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, response: responseText })
        });
        if (res.ok) { toast("Hecho"); loadInfractionsAndAppeals(); }
        else { const data = await res.json(); throw new Error(data.detail); }
    } catch (e) { toast(e.message || "Error", "error"); }
}

async function saveAllConfig() {
    if (!currentGuildId) return;
    const merge = (key, patch) => {
        serverConfigData[key] = { ...(serverConfigData[key] || {}), ...patch };
    };
    serverConfigData.prefix = document.getElementById("cfg-prefix").value;
    serverConfigData.lang = document.getElementById("cfg-lang").value;
    serverConfigData.language = serverConfigData.lang;
    const levelNumber = (id, fallback) => {
        const raw = document.getElementById(id)?.value;
        if (raw === undefined || raw === "") return fallback;
        const value = Number(raw);
        return Number.isFinite(value) ? value : fallback;
    };
    merge("leveling", {
        enabled: document.getElementById("cfg-leveling-enabled").checked,
        text_xp: { min: parseInt(document.getElementById("cfg-tx-min").value), max: parseInt(document.getElementById("cfg-tx-max").value) },
        voice_xp: { min: parseInt(document.getElementById("cfg-vx-min").value), max: parseInt(document.getElementById("cfg-vx-max").value) },
        level_up_channel: document.getElementById("cfg-lvl-channel").value || "",
        leaderboard_channel: document.getElementById("cfg-lead-channel").value || "",
        card_custom_text: document.getElementById("cfg-level-card-custom")?.value || "",
        card_layout: {
            avatar_x: levelNumber("cfg-level-avatar-x", 158),
            avatar_y: levelNumber("cfg-level-avatar-y", 200),
            avatar_size: levelNumber("cfg-level-avatar-size", 220),
            name_x: levelNumber("cfg-level-name-x", 310),
            name_y: levelNumber("cfg-level-name-y", 48),
            rank_x: levelNumber("cfg-level-rank-x", 310),
            rank_y: levelNumber("cfg-level-rank-y", 118),
            level_x: levelNumber("cfg-level-level-x", 1152),
            level_y: levelNumber("cfg-level-level-y", 40),
            bar_x: levelNumber("cfg-level-bar-x", 310),
            bar_y: levelNumber("cfg-level-bar-y", 250),
            bar_width: levelNumber("cfg-level-bar-width", 830),
            bar_height: levelNumber("cfg-level-bar-height", 44),
            custom_x: levelNumber("cfg-level-custom-x", 720),
            custom_y: levelNumber("cfg-level-custom-y", 345),
            custom_size: levelNumber("cfg-level-custom-size", 28)
        }
    });
    serverConfigData.premium_persona = {
        name: $("cfg-premium-bot-name")?.value.trim() || "",
        avatar: $("cfg-premium-bot-avatar")?.value.trim() || ""
    };
    serverConfigData.chatbot = {
        enabled: $("cfg-ai-enabled") ? $("cfg-ai-enabled").checked : false,
        personality_prompt: document.getElementById("cfg-ai-prompt").value,
        toxicity_threshold: parseFloat(document.getElementById("cfg-ai-toxicity").value),
        channel_ids: ($("cfg-ai-channels") && $("cfg-ai-channels").value || "").split(/[,\s]+/).filter(Boolean)
    };
    merge("achievements", {
        enabled: $("cfg-achievements-enabled") ? $("cfg-achievements-enabled").checked : false
    });
    merge("logs", {
        messages: document.getElementById("cfg-log-messages").value || "",
        moderation: document.getElementById("cfg-log-moderation").value || "",
        voice: document.getElementById("cfg-log-voice").value || "",
        members: document.getElementById("cfg-log-members").value || "",
        joins: document.getElementById("cfg-log-joins").value || "",
        alts: (document.getElementById("cfg-log-alts") && document.getElementById("cfg-log-alts").value) || "",
        hijack: ($("cfg-log-hijack") && $("cfg-log-hijack").value) || "",
        tickets: ($("cfg-log-tickets") && $("cfg-log-tickets").value) || ($("cfg-ticket-transcript") && $("cfg-ticket-transcript").value) || "",
        verification: ($("cfg-log-verification") && $("cfg-log-verification").value) || (serverConfigData.logs && serverConfigData.logs.verification) || "",
        server: (serverConfigData.logs && serverConfigData.logs.server) || ""
    });
    const designed = collectTicketDesigner();
    const ticketsPatch = {
        category_name: document.getElementById("cfg-ticket-category").value || "Tickets",
        transcript_channel_id: document.getElementById("cfg-ticket-transcript").value
            || ($("cfg-log-tickets") && $("cfg-log-tickets").value)
            || "",
        categories: (ticketDesignerReady && designed.categories.length)
            ? designed.categories
            : (serverConfigData.tickets && serverConfigData.tickets.categories) || []
    };
    if (ticketDesignerReady) ticketsPatch.panel = designed.panel;
    merge("tickets", ticketsPatch);
    merge("moderation", {
        ...(serverConfigData.moderation || {}),
        escalate: {
            enabled: $("cfg-esc-enabled") ? $("cfg-esc-enabled").checked : false,
            warns_timeout: parseInt($("cfg-esc-to") && $("cfg-esc-to").value) || 3,
            timeout_minutes: parseInt($("cfg-esc-mins") && $("cfg-esc-mins").value) || 30,
            warns_kick: parseInt($("cfg-esc-kick") && $("cfg-esc-kick").value) || 5,
            window_hours: parseInt($("cfg-esc-window") && $("cfg-esc-window").value) || 24
        }
    });
    merge("automod", {
        enabled: document.getElementById("cfg-automod-enabled").checked,
        block_invites: document.getElementById("cfg-automod-block-invites").checked,
        auto_warn: document.getElementById("cfg-automod-auto-warn").checked,
        mention_limit: parseInt(document.getElementById("cfg-automod-mentions").value) || 5,
        spam_threshold: parseInt(document.getElementById("cfg-automod-spam-threshold").value) || 3,
        hijack: !$("cfg-automod-hijack") || $("cfg-automod-hijack").checked,
        hijack_timeout: !$("cfg-automod-hijack-timeout") || $("cfg-automod-hijack-timeout").checked,
        links: collectLinksConfig()
    });
    const welcomeNumber = (id, fallback) => {
        const raw = document.getElementById(id)?.value;
        if (raw === undefined || raw === "") return fallback;
        const value = Number(raw);
        return Number.isFinite(value) ? value : fallback;
    };
    merge("welcome", {
        enabled: document.getElementById("cfg-welcome-enabled").checked,
        channel_id: document.getElementById("cfg-welcome-channel").value || "",
        message: document.getElementById("cfg-welcome-msg").value,
        card_heading: document.getElementById("cfg-welcome-heading").value || "BIENVENIDO",
        member_label: document.getElementById("cfg-welcome-member-label").value || "Miembro",
        custom_text: document.getElementById("cfg-welcome-custom-text")?.value || "",
        layout: {
            avatar_x: welcomeNumber("cfg-welcome-avatar-x", 512),
            avatar_y: welcomeNumber("cfg-welcome-avatar-y", 205),
            avatar_size: welcomeNumber("cfg-welcome-avatar-size", 220),
            heading_x: welcomeNumber("cfg-welcome-heading-x", 512),
            heading_y: welcomeNumber("cfg-welcome-heading-y", 330),
            name_x: welcomeNumber("cfg-welcome-name-x", 512),
            name_y: welcomeNumber("cfg-welcome-name-y", 391),
            member_x: welcomeNumber("cfg-welcome-member-x", 512),
            member_y: welcomeNumber("cfg-welcome-member-y", 435),
            custom_x: welcomeNumber("cfg-welcome-custom-x", 512),
            custom_y: welcomeNumber("cfg-welcome-custom-y", 60),
            custom_size: welcomeNumber("cfg-welcome-custom-size", 26)
        }
    });
    merge("goodbye", {
        enabled: document.getElementById("cfg-goodbye-enabled").checked,
        channel_id: document.getElementById("cfg-goodbye-channel").value || "",
        message: document.getElementById("cfg-goodbye-msg").value
    });
    merge("starboard", {
        enabled: document.getElementById("cfg-star-enabled").checked,
        channel_id: document.getElementById("cfg-star-channel").value || "",
        limit: parseInt(document.getElementById("cfg-star-limit").value) || 3
    });
    merge("economy", {
        enabled: document.getElementById("cfg-eco-enabled").checked,
        currency_symbol: document.getElementById("cfg-eco-symbol").value || "🦞"
    });
    merge("suggestions", {
        channel: $("cfg-suggestions-channel")?.value || "",
        auto_approve_threshold: parseInt($("cfg-suggestions-threshold")?.value) || 10
    });
    merge("moderation", {
        appeals_channel: $("cfg-mod-appeals-channel")?.value || "",
        mute_role_id: $("cfg-mod-mute-role")?.value || ""
    });
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(serverConfigData)
        });
        await fetch(`/api/guilds/${currentGuildId}/antiraid`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                enabled: document.getElementById("cfg-raid-enabled").checked,
                join_threshold: parseInt(document.getElementById("cfg-raid-threshold").value) || 10,
                window_seconds: parseInt(document.getElementById("cfg-raid-window").value) || 10,
                lockdown_minutes: parseInt(document.getElementById("cfg-raid-lock").value) || 5,
                alert_channel_id: document.getElementById("cfg-raid-channel").value || ""
            })
        });
        if ($("cfg-nuke-enabled")) {
            await fetch(`/api/guilds/${currentGuildId}/antinuke`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    enabled: $("cfg-nuke-enabled").checked,
                    action: $("cfg-nuke-action")?.value || "strip_roles",
                    log_channel_id: $("cfg-nuke-channel")?.value || "",
                    max_channel_deletes: parseInt($("cfg-nuke-channels")?.value) || 3,
                    max_role_deletes: parseInt($("cfg-nuke-roles")?.value) || 3,
                    max_bans: parseInt($("cfg-nuke-bans")?.value) || 5,
                    max_kicks: parseInt($("cfg-nuke-kicks")?.value) || 5,
                    window_seconds: parseInt($("cfg-nuke-window")?.value) || 10
                })
            });
        }
        if (res.ok) toast("Guardado. El bot lo aplica al momento.");
        else throw new Error();
    } catch {
        toast(t("toast.save_error"), "error");
    }
}

async function saveChatbotToggle() {
    if (!currentGuildId || !$("cfg-ai-enabled")) return;
    if (!serverConfigData.chatbot) serverConfigData.chatbot = {};
    serverConfigData.chatbot.enabled = $("cfg-ai-enabled").checked === true;
    serverConfigData.chatbot.personality_prompt = ($("cfg-ai-prompt") && $("cfg-ai-prompt").value) || "";
    serverConfigData.chatbot.toxicity_threshold = parseFloat(($("cfg-ai-toxicity") && $("cfg-ai-toxicity").value) || "0.8");
    serverConfigData.chatbot.channel_ids = ($("cfg-ai-channels") && $("cfg-ai-channels").value || "").split(/[,\s]+/).filter(Boolean);
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(serverConfigData)
        });
        if (!res.ok) throw new Error();
        toast(serverConfigData.chatbot.enabled ? "IA activada. El bot lo aplica al momento." : "IA desactivada.", "success");
    } catch {
        toast(t("toast.save_error"), "error");
    }
}

let ticketDesignerReady = false;

function emptyTicketType() {
    return { label: "", emoji: "📩", description: "", category: "Tickets", image: "", price: "", details: "" };
}

function fillTicketDesigner(tickets) {
    const t = tickets || {};
    const panel = t.panel || {};
    if ($("tp-title")) $("tp-title").value = panel.title || "";
    if ($("tp-desc")) $("tp-desc").value = panel.description || "";
    if ($("tp-image")) $("tp-image").value = panel.image || "";
    if ($("tp-thumb")) $("tp-thumb").value = panel.thumbnail || "";
    if ($("tp-footer")) $("tp-footer").value = panel.footer || "";
    if ($("tp-color")) {
        let col = panel.color;
        if (typeof col === "number") col = "#" + col.toString(16).padStart(6, "0");
        if (!col || typeof col !== "string" || !col.startsWith("#")) col = "#00ff88";
        $("tp-color").value = col;
    }
    const cats = (t.categories && t.categories.length) ? t.categories : [emptyTicketType()];
    renderTicketTypeCards(cats);
    ticketDesignerReady = true;
}

function renderTicketTypeCards(cats) {
    const box = $("ticket-type-cards");
    if (!box) return;
    box.innerHTML = "";
    (cats || []).forEach((c, i) => {
        const card = document.createElement("div");
        card.className = "ticket-type-card stack";
        card.dataset.idx = String(i);
        const img = (c.image || "").replace(/"/g, "");
        card.innerHTML = `
            <div class="toolbar" style="margin:0">
                <b>${t("dash.option_n", {n: i + 1})}</b>
                <button type="button" class="btn btn-ghost btn-sm" onclick="removeTicketType(${i})">${t("dash.remove")}</button>
            </div>
            <div class="row">
                <div class="field"><label>${t("dash.ticket.name")}</label><input class="tt-label" value="${esc(c.label || "")}" placeholder="Netflix 4K"></div>
                <div class="field"><label>${t("dash.ticket.emoji")}</label><input class="tt-emoji" value="${esc(c.emoji || "📩")}"></div>
            </div>
            <div class="row">
                <div class="field"><label>${t("dash.ticket.desc_label")}</label><input class="tt-desc" value="${esc(c.description || "")}" placeholder="1 mes · 7,99€"></div>
                <div class="field"><label>${t("dash.ticket.price")}</label><input class="tt-price" value="${esc(c.price || "")}" placeholder="7,99€"></div>
            </div>
            <div class="field"><label>${t("dash.ticket.folder")}</label><input class="tt-folder" value="${esc(c.category || "")}" placeholder="Tickets · Pedidos"></div>
            <div class="field"><label>${t("dash.ticket.detail_label")}</label><textarea class="tt-details" rows="2" placeholder="Qué incluye, cómo se entrega…">${esc(c.details || "")}</textarea></div>
            <div class="row">
                <div class="field"><label>${t("dash.ticket.image")}</label><input class="tt-image" value="${esc(c.image || "")}" placeholder="https://…" oninput="previewTicketImage(this)"></div>
                <div>${img ? `<img class="preview" src="${img}" alt="">` : ""}</div>
            </div>`;
        box.appendChild(card);
    });
}

function previewTicketImage(input) {
    const wrap = input.parentElement.nextElementSibling;
    if (!wrap) return;
    const url = (input.value || "").trim();
    wrap.innerHTML = url.startsWith("https://") ? `<img class="preview" src="${url.replace(/"/g, "")}" alt="">` : "";
}

function collectTicketDesigner() {
    const panel = {
        title: ($("tp-title") && $("tp-title").value.trim()) || "🎫 Tickets",
        description: ($("tp-desc") && $("tp-desc").value.trim()) || "",
        color: ($("tp-color") && $("tp-color").value) || "#00ff88",
        image: ($("tp-image") && $("tp-image").value.trim()) || "",
        thumbnail: ($("tp-thumb") && $("tp-thumb").value.trim()) || "",
        footer: ($("tp-footer") && $("tp-footer").value.trim()) || "Dabot · dabot.davito.es"
    };
    const categories = [];
    document.querySelectorAll("#ticket-type-cards .ticket-type-card").forEach(card => {
        const label = (card.querySelector(".tt-label") && card.querySelector(".tt-label").value.trim()) || "";
        if (!label) return;
        const item = {
            label,
            emoji: (card.querySelector(".tt-emoji") && card.querySelector(".tt-emoji").value.trim()) || "📩",
            description: (card.querySelector(".tt-desc") && card.querySelector(".tt-desc").value.trim()) || label,
            category: (card.querySelector(".tt-folder") && card.querySelector(".tt-folder").value.trim()) || (`Tickets · ${label}`),
            price: (card.querySelector(".tt-price") && card.querySelector(".tt-price").value.trim()) || "",
            details: (card.querySelector(".tt-details") && card.querySelector(".tt-details").value.trim()) || "",
            image: (card.querySelector(".tt-image") && card.querySelector(".tt-image").value.trim()) || ""
        };
        categories.push(item);
    });
    return { panel, categories };
}

function addTicketType() {
    const { panel, categories } = collectTicketDesigner();
    categories.push(emptyTicketType());
    fillTicketDesigner({ panel, categories });
}

function removeTicketType(i) {
    const { panel, categories } = collectTicketDesigner();
    categories.splice(i, 1);
    fillTicketDesigner({ panel, categories: categories.length ? categories : [emptyTicketType()] });
}

async function ensureTicketDesigner() {
    if (ticketDesignerReady && $("ticket-type-cards") && $("ticket-type-cards").children.length) return;
    if (!currentGuildId) return;
    try {
        const cfg = await (await fetch(`/api/guilds/${currentGuildId}/config`)).json();
        fillTicketDesigner((cfg && cfg.tickets) || {});
    } catch (e) {
        fillTicketDesigner({});
    }
}

async function publishTicketDesigner() {
    if (!currentGuildId) return;
    const channel_id = $("tp-publish-channel") && $("tp-publish-channel").value;
    if (!channel_id) return toast("Elige un canal para el panel", "warning");
    const designed = collectTicketDesigner();
    if (!designed.categories.length) return toast("Añade al menos una opción", "warning");
    try {
        serverConfigData.tickets = { ...(serverConfigData.tickets || {}), panel: designed.panel, categories: designed.categories };
        const resSave = await fetch(`/api/guilds/${currentGuildId}/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(serverConfigData)
        });
        if (!resSave.ok) throw new Error("save");
        const res = await fetch(`/api/guilds/${currentGuildId}/actions/ticket-panel`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ channel_id })
        });
        toast(res.ok ? "Panel publicado en Discord" : "Guardado, pero no se pudo publicar (permisos / canal)", res.ok ? "success" : "error");
    } catch (e) {
        toast("No se pudo guardar o publicar", "error");
    }
}

async function sendTicketPanel() {
    const channel_id = document.getElementById("action-ticket-channel").value;
    if (!channel_id) return toast("Elige un canal", "warning");
    const res = await fetch(`/api/guilds/${currentGuildId}/actions/ticket-panel`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id })
    });
    toast(res.ok ? t("dash.toast.ticket_published") : t("dash.toast.publish_failed"), res.ok ? "success" : "error");
}

async function sendVerifyPanel() {
    const channel_id = document.getElementById("action-verify-channel").value;
    if (!channel_id) return toast("Elige un canal", "warning");
    const res = await fetch(`/api/guilds/${currentGuildId}/actions/verification-panel`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id })
    });
    toast(res.ok ? t("toast.verify.ok") : t("toast.verify.err"), res.ok ? "success" : "error");
}

async function loadAdminDiagnostics() {
    try {
        const data = await (await fetch("/api/admin/diagnostics")).json();
        setText("diag-lvl-count", data.total_level_records);
        setText("diag-u-count", data.premium_users_count);
        setText("diag-g-count", data.premium_guilds_count);
        setText("diag-bot-guilds", data.bot_guilds);
        setText("diag-alt-pending", data.alt_cases_pending);
        setText("diag-alt-sights", data.alt_sightings);
        setText("diag-verify-people", data.verifications_people);
        const plist = $("adm-premium-list");
        if (plist) {
            const g = data.premium_guilds || [];
            plist.innerHTML = g.length ? g.map(p => `<div class="switch-row"><div><b>${p.guild_id}</b><p>${p.label || p.plan} · ${p.active ? t("dash.active") : t("dash.expired")} · ${String(p.expires_at || "").slice(0,10)}</p></div></div>`).join("") : `<p class="sub">${t("dash.empty.premium_none")}</p>`;
        }
    } catch (e) { console.error(e); }
}

function htmlEscape(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
}

let liveLogsInterval = null;
let currentLogFilename = "";

async function loadAdminLiveLogs() {
    const term = $("live-logs-terminal");
    const linesSelect = $("live-logs-lines");
    const lines = linesSelect ? linesSelect.value : 200;
    try {
        const res = await fetch(`/api/admin/live-logs?lines=${lines}`);
        if (!res.ok) {
            if (term) term.innerText = `Error cargando logs: ${res.status} ${res.statusText}`;
            return;
        }
        const data = await res.json();
        currentLogFilename = data.filename || "";
        const sub = $("live-logs-sub");
        if (sub && data.filename) {
            sub.innerText = `Archivo activo: ${data.filename} (${data.returned_lines} de ${data.total_lines} líneas)`;
        }
        if (!term) return;
        if (!data.lines || data.lines.length === 0) {
            term.innerText = "No hay registros disponibles en este momento.";
            return;
        }

        const formatted = data.lines.map(line => {
            const escaped = htmlEscape(line);
            if (line.includes("[ERROR]") || line.includes("CRITICAL")) {
                return `<span style="color:#ff7b72">${escaped}</span>`;
            } else if (line.includes("[WARNING]")) {
                return `<span style="color:#d29922">${escaped}</span>`;
            } else if (line.includes("[INFO]")) {
                return `<span style="color:#7ee787">${escaped}</span>`;
            } else if (line.includes("[DEBUG]")) {
                return `<span style="color:#8b949e">${escaped}</span>`;
            }
            return escaped;
        }).join("\n");

        const wasAtBottom = term.scrollHeight - term.clientHeight <= term.scrollTop + 60;
        term.innerHTML = formatted;
        if (wasAtBottom) {
            term.scrollTop = term.scrollHeight;
        }
    } catch (e) {
        if (term) term.innerText = `Error de conexión: ${e.message}`;
    }
}

function toggleLiveLogsAuto(enable) {
    if (liveLogsInterval) {
        clearInterval(liveLogsInterval);
        liveLogsInterval = null;
    }
    const badge = $("live-logs-badge");
    const check = $("live-logs-auto");
    if (check) check.checked = Boolean(enable);
    if (enable) {
        if (badge) {
            badge.innerText = "En vivo";
            badge.style.color = "var(--green)";
            badge.style.background = "rgba(0,255,136,0.15)";
        }
        liveLogsInterval = setInterval(() => {
            const adminView = $("view-admin");
            if (adminView && !adminView.classList.contains("hidden")) {
                loadAdminLiveLogs();
            } else {
                clearInterval(liveLogsInterval);
                liveLogsInterval = null;
            }
        }, 5000);
    } else {
        if (badge) {
            badge.innerText = "Pausado";
            badge.style.color = "var(--warn)";
            badge.style.background = "rgba(255,193,7,0.15)";
        }
    }
}

function downloadCurrentLog() {
    const term = $("live-logs-terminal");
    if (!term) return;
    const text = term.innerText;
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = currentLogFilename || "dabot_session.log";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function loadAdminAnnouncements() {
    const list = $("adm-announcement-guilds");
    if (!list) return;
    try {
        const res = await fetch("/api/admin/announcements");
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || t("dash.config_load_fail"));
        list.innerHTML = data.length ? data.map(g => {
            const options = [`<option value="">Predeterminado (general)</option>`].concat((g.channels || []).map(ch =>
                `<option value="${htmlEscape(ch.id)}" ${String(ch.id) === String(g.configured_channel_id || "") ? "selected" : ""}>#${htmlEscape(ch.name)} (${htmlEscape(ch.id)})</option>`
            )).join("");
            const effective = g.effective_channel ? t("dash.now_channel", {name: htmlEscape(g.effective_channel.name)}) : t("dash.no_channel");
            return `<div class="switch-row"><div><b>${htmlEscape(g.guild_name)}</b><p class="mono">${htmlEscape(g.guild_id)} · ${effective}</p></div><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><select id="adm-ann-channel-${htmlEscape(g.guild_id)}">${options}</select><button class="btn btn-ghost btn-sm" onclick="saveAnnouncementChannel('${htmlEscape(g.guild_id)}')">Guardar</button></div></div>`;
        }).join("") : `<div class="empty">${t("dash.bot_no_guilds")}</div>`;
        loadRecentAnnouncements();
    } catch (e) {
        list.innerHTML = `<div class="empty">${htmlEscape(e.message || t("dash.empty.load_fail"))}</div>`;
    }
}

async function loadRecentAnnouncements() {
    const list = $("adm-announcement-recent");
    if (!list) return;
    try {
        const res = await fetch("/api/admin/announcements/recent");
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || t("dash.history_load_fail"));
        list.innerHTML = data.length ? `<h4 style="margin-bottom:0">${t("dash.announce.recent")}</h4>` + data.map(a =>
            `<div class="switch-row"><div style="flex:1;min-width:240px"><p class="mono">${htmlEscape(a.created_at)} · ${t("dash.announce.delivered_line", {sent:a.sent, total:a.total})}</p><textarea id="adm-ann-edit-${htmlEscape(a.source_message_id)}" rows="2" maxlength="2000">${htmlEscape(a.content)}</textarea></div><button class="btn btn-ghost btn-sm" onclick="editGlobalAnnouncement('${htmlEscape(a.source_message_id)}')">Guardar edición</button></div>`
        ).join("") : "";
    } catch (e) { console.error(e); }
}

async function editGlobalAnnouncement(sourceId) {
    const input = document.getElementById(`adm-ann-edit-${sourceId}`);
    const content = (input?.value || "").trim();
    if (!content) return toast("El anuncio no puede estar vacío", "warning");
    const res = await fetch(`/api/admin/announcements/${encodeURIComponent(sourceId)}`, {
        method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({content})
    });
    const data = await res.json().catch(() => ({}));
    toast(res.ok ? `Edición aplicada: ${data.edited || 0} correctos, ${data.failed || 0} fallidos` : (data.detail || t("dash.edit_fail")), res.ok ? "success" : "error");
    if (res.ok) loadRecentAnnouncements();
}

async function saveAnnouncementChannel(guildId) {
    const select = document.getElementById(`adm-ann-channel-${guildId}`);
    const res = await fetch(`/api/admin/announcements/config/${guildId}`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({channel_id: select ? (select.value || null) : null})
    });
    const data = await res.json().catch(() => ({}));
    toast(res.ok ? t("dash.announce.channel_saved") : (data.detail || "No se pudo guardar"), res.ok ? "success" : "error");
    if (res.ok) loadAdminAnnouncements();
}

async function sendGlobalAnnouncement() {
    const input = $("adm-announcement-content");
    const content = (input?.value || "").trim();
    if (!content) return toast("Escribe un anuncio", "warning");
    const result = await Swal.fire({title: t("dash.announce.send_all_title"), text: t("dash.announce.send_all_text"), icon: "warning", showCancelButton: true, background: "#111a30", color: "#fff"});
    if (!result.isConfirmed) return;
    const res = await fetch("/api/admin/announcements/send", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({content})
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
        input.value = "";
        const extra = (data.failures && data.failures.length)
            ? " · " + data.failures.slice(0, 3).map(f => `${f.guild_name || f.guild_id}: ${(f.error || "").slice(0, 80)}`).join(" · ")
            : "";
        toast(`Anuncio enviado: ${data.delivered || 0} correctos, ${data.failed || 0} fallidos${extra}`, data.failed ? "warning" : "success");
    } else toast(data.detail || t("dash.announce_fail"), "error");
}

let adminGuildsCache = {};

async function loadAdminBotGuilds() {
    try {
        const guilds = await (await fetch("/api/admin/bot-guilds")).json();
        const list = document.getElementById("admin-bot-guilds-list");
        if (!list) return;
        list.innerHTML = "";
        if (!Array.isArray(guilds) || !guilds.length) {
            list.innerHTML = `<div class="empty">${t("dash.bot_no_guilds")}</div>`;
            return;
        }
        guilds.forEach(g => {
            adminGuildsCache[g.id] = g;
            guildsCache[g.id] = Object.assign({}, guildsCache[g.id] || {}, g, { user_role: "owner", via_bot: g.via_bot !== false });
            const iconUrl = g.icon
                ? `https://cdn.discordapp.com/icons/${g.id}/${g.icon}.png`
                : "https://cdn.discordapp.com/embed/avatars/0.png";
            const pending = g.pending_alts ? `<span class="pill risk-high">${g.pending_alts} pendientes</span>` : "";
            const members = g.member_count ? `${g.member_count} miembros` : `${g.active_users} XP`;
            const safeName = (g.name || "").replace(/</g, "").replace(/'/g, "");
            const premiumBtn = g.is_premium
                ? `<button class="btn btn-ghost btn-sm" onclick="quickGuildPremium('${g.id}', false)">Quitar Premium</button>`
                : `<button class="btn btn-primary btn-sm" onclick="quickGuildPremium('${g.id}', true)">Dar Premium</button>`;
            list.insertAdjacentHTML("beforeend", `<div class="switch-row adm-guild-row" data-name="${(g.name || "").toLowerCase()} ${g.id}">
                <div style="display:flex;gap:10px;align-items:center;min-width:0">
                    <img src="${iconUrl}" width="32" height="32" style="border-radius:8px" alt="">
                    <div style="min-width:0"><b>${safeName}</b><div class="mono">${g.id} · ${members}</div></div>
                    ${g.is_premium ? '<span class="pill vip">Premium</span>' : ""}
                    ${pending}
                </div>
                <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                    <label class="sub" style="margin:0;display:flex;gap:6px;align-items:center">
                        <input type="checkbox" ${g.alt_share ? "checked" : ""} onchange="toggleAltShare('${g.id}', this.checked)"> Red alts
                    </label>
                    ${premiumBtn}
                    <button class="btn btn-primary btn-sm" onclick="openAdminGuild('${g.id}')">Abrir panel</button>
                    <button class="btn btn-ghost btn-sm" onclick="createRemoteInvite('${g.id}')"><i class="fas fa-user-plus"></i> Invitación</button>
                    <button class="btn btn-ghost btn-sm" onclick="liveSelectGuild('${g.id}')">Ver chat</button>
                    <button class="btn btn-danger btn-sm" onclick="forceLeaveGuild('${g.id}')">Salir</button>
                </div>
            </div>`);
        });
        fillLiveGuildSelect(guilds);
        const q = $("adm-guild-search");
        if (q && q.value) filterAdminGuilds(q.value);
    } catch (e) { console.error(e); }
}

async function createRemoteInvite(guildId, guildName) {
    guildName = guildName || (guildsCache[guildId] && guildsCache[guildId].name) || (adminGuildsCache[guildId] && adminGuildsCache[guildId].name) || guildId;
    toast("Generando invitación remota...", "info");
    try {
        const res = await fetch(`/api/admin/guilds/${guildId}/create-invite`, { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            Swal.fire({
                title: "Error al crear invitación",
                text: data.detail || "No se pudo generar la invitación para este servidor.",
                icon: "error",
                background: "#111a30",
                color: "#fff"
            });
            return;
        }

        const inviteUrl = data.url;
        const isExisting = data.source === "existing";
        const subtitle = isExisting ? "Invitación existente en el servidor:" : "Enlace de invitación generado (válido por 24h):";

        Swal.fire({
            title: `🎉 Invitación para ${htmlEscape(guildName)}`,
            html: `
                <p style="margin-bottom:12px;font-size:14px;color:#94a3b8;">${subtitle}</p>
                <input id="swal-invite-url" readonly value="${htmlEscape(inviteUrl)}" style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#1e293b;color:#38bdf8;font-family:monospace;text-align:center;font-size:15px;margin-bottom:14px;">
                <div style="display:flex;gap:10px;justify-content:center">
                    <button type="button" class="btn btn-primary btn-sm" onclick="navigator.clipboard.writeText('${htmlEscape(inviteUrl)}'); toast('¡Enlace copiado al portapapeles!', 'success');">📋 Copiar enlace</button>
                    <a href="${htmlEscape(inviteUrl)}" target="_blank" class="btn btn-ghost btn-sm" style="text-decoration:none">🚀 Abrir enlace</a>
                </div>
            `,
            showConfirmButton: false,
            showCloseButton: true,
            background: "#111a30",
            color: "#fff"
        });
    } catch (e) {
        toast("Error de conexión al generar la invitación.", "error");
    }
}

function filterAdminGuilds(q) {
    q = (q || "").toLowerCase();
    document.querySelectorAll(".adm-guild-row").forEach(row => {
        row.style.display = !q || (row.dataset.name || "").includes(q) ? "" : "none";
    });
}

function openAdminGuild(guildId) {
    const g = adminGuildsCache[guildId] || guildsCache[guildId] || { id: guildId, name: guildId, user_role: "owner", via_bot: true };
    selectGuild(guildId, g);
}

async function forceLeaveGuild(guildId, guildName) {
    guildName = guildName || (adminGuildsCache[guildId] && adminGuildsCache[guildId].name) || (guildsCache[guildId] && guildsCache[guildId].name) || guildId;
    const { isConfirmed } = await Swal.fire({
        title: t("dash.leave_title"), text: guildName, icon: "warning",
        showCancelButton: true, confirmButtonColor: "#fb7185", background: "#111a30", color: "#fff"
    });
    if (!isConfirmed) return;
    const res = await fetch(`/api/admin/guilds/${guildId}/leave`, { method: "POST" });
    toast(res.ok ? "El bot ha salido" : "Error", res.ok ? "success" : "error");
    if (res.ok) loadAdminBotGuilds();
}

function renderHealth(health, premium, isPremium) {
    const box = $("health-list");
    const score = $("health-score");
    if (score) score.innerText = health ? `${health.score}%` : (isPremium ? "Premium" : "—");
    if (!box) return;
    const items = (health && health.items) || [];
    if (!items.length) {
        box.innerHTML = "";
        return;
    }
    box.innerHTML = items.map(i => `<div class="switch-row">
        <div><b>${i.ok ? "✅" : "—"} ${i.label}</b><p>${i.hint || ""}</p></div>
        ${i.premium ? `<span class="pill vip">${isPremium ? t("dash.active") : t("dash.free_pill")}</span>` : ""}
    </div>`).join("");
}

async function loadTickets() {
    if (!currentGuildId) return;
    const body = $("tickets-table-body");
    const status = ($("tickets-filter") && $("tickets-filter").value) || "";
    if (body) body.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.loading")}</td></tr>`;
    try {
        const q = status ? `?status=${encodeURIComponent(status)}` : "";
        const data = await (await fetch(`/api/guilds/${currentGuildId}/tickets${q}`)).json();
        const rows = data.tickets || [];
        if (!body) return;
        body.innerHTML = rows.length ? rows.map(t => `<tr>
            <td class="mono">#${t.id}</td>
            <td>${(t.opener_name || t.opener_id || "").replace(/</g,"")}</td>
            <td><span class="pill">${t.status}</span></td>
            <td class="mono">${(t.created_at || "").replace("T"," ").slice(0,16)}</td>
            <td><button class="btn btn-ghost btn-sm" onclick="openTicket(${t.id})">Ver</button></td>
        </tr>`).join("") : `<tr><td colspan="5" class="empty">Sin tickets. Publica el panel en Resumen.</td></tr>`;
    } catch (e) {
        if (body) body.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.tickets_fail")}</td></tr>`;
    }
    loadTicketRatings();
}

async function loadTicketRatings() {
    if (!currentGuildId) return;
    const avgEl = $("csat-avg-score");
    const countEl = $("csat-total-reviews");
    const staffBody = $("csat-staff-body");
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/ticket_ratings`);
        if (!res.ok) return;
        const data = await res.json();
        if (avgEl) avgEl.textContent = (data.average_csat || 0) > 0 ? `⭐ ${data.average_csat} / 5.0` : `— / 5.0`;
        if (countEl) countEl.textContent = `${data.total_reviews || 0} valoraciones`;
        if (staffBody && data.leaderboard) {
            staffBody.innerHTML = data.leaderboard.length ? data.leaderboard.map((s, idx) => `
                <tr>
                    <td><strong>#${idx + 1}</strong> ${(s.staff_name || "Equipo").replace(/</g,"")}</td>
                    <td><span class="pill" style="color:var(--gold,#f59e0b);">⭐ ${s.avg_rating}</span></td>
                    <td>${s.total_reviews} tickets</td>
                </tr>
            `).join("") : `<tr><td colspan="3" class="empty">Aún no hay valoraciones de staff registradas.</td></tr>`;
        }
    } catch(e) {}
}


async function openTicket(id, silent = false) {
    const box = $("ticket-thread");
    if (!box) return;
    box.dataset.ticketId = id;
    if (!silent) {
        box.classList.remove("hidden");
        box.innerHTML = `<p class="sub">${t("dash.empty.loading")}</p>`;
    }
    try {
        const data = await (await fetch(`/api/guilds/${currentGuildId}/tickets/${id}`)).json();
        const t = data.ticket || {};
        const msgs = data.messages || [];
        const escape = (s) => String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
        const lines = msgs.map(m => {
            const atts = (m.attachments || []).map(a => {
                const url = a.url || "";
                const name = escape(a.filename || "archivo");
                const isImg = /\.(png|jpe?g|gif|webp)(\?|$)/i.test(url) || (a.content_type || "").startsWith("image/");
                if (isImg) return `<a href="${url}" target="_blank"><img src="${url}" alt="${name}" style="max-width:220px;border-radius:10px;display:block;margin-top:6px"></a>`;
                return `<a href="${url}" target="_blank">${name}</a>`;
            }).join(" ");
            const body = m.deleted ? `<s>${escape(m.content)}</s>` : escape(m.content);
            const edit = m.edited && m.previous_content
                ? `<p class="sub">Antes: <s>${escape(m.previous_content)}</s></p>` : (m.edited ? `<p class="sub">editado</p>` : "");
            return `<div class="switch-row" style="align-items:flex-start">
                <div><b>${escape(m.username || m.user_id)}</b> <span class="mono">${escape(m.user_id || "")}</span>
                <p style="white-space:pre-wrap;margin-top:4px">${body}</p>${edit}${atts}</div>
                <span class="mono">${(m.created_at || "").replace("T"," ").slice(0,16)}</span>
            </div>`;
        }).join("") || `<p class="empty">${t("dash.empty.messages")}</p>`;
        const webLink = `${location.origin}/dashboard?guild=${currentGuildId}&ticket=${t.id}`;
        const transcriptUrl = `/tickets/${t.id}/transcript`;

        // Action footer
        let actionFooter = "";
        if (t.status !== "closed") {
            const currentVal = $("ticket-reply-text") ? $("ticket-reply-text").value : "";
            actionFooter = `
                <div class="panel glass stack" style="margin-top:16px;background:rgba(12,20,38,0.85);border:1px solid rgba(0,255,136,0.25)">
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                        <h4 style="margin:0;color:var(--text-bright)"><i class="fas fa-reply" style="color:var(--green)"></i> Responder en directo a Discord</h4>
                        <span class="live-sync-badge" style="font-size:10px"><span class="pulse-ring"></span> Sincronizado</span>
                    </div>
                    <textarea id="ticket-reply-text" rows="3" placeholder="Escribe tu respuesta para enviarla directamente al canal de Discord..." style="width:100%;resize:vertical">${escape(currentVal)}</textarea>
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
                        <span class="sub" style="margin:0;font-size:12px"><i class="fab fa-discord" style="color:var(--discord)"></i> El mensaje aparecerá al instante en Discord con tu autoría.</span>
                        <div style="display:flex;gap:8px">
                            <button class="btn btn-danger btn-sm" onclick="closeCurrentTicket(${t.id})"><i class="fas fa-lock"></i> Cerrar Ticket</button>
                            <button class="btn btn-primary btn-sm" onclick="sendTicketReply(${t.id})"><i class="fas fa-paper-plane"></i> Enviar a Discord</button>
                        </div>
                    </div>
                </div>
            `;
        } else {
            actionFooter = `
                <div class="panel glass" style="margin-top:16px;background:rgba(236,72,153,0.08);border:1px solid rgba(236,72,153,0.3);text-align:center;padding:14px">
                    <span style="color:#ec4899;font-weight:700"><i class="fas fa-lock"></i> Este ticket está cerrado · Finalizado por ${escape(t.closed_name || 'Staff')}</span>
                </div>
            `;
        }

        if (silent && document.activeElement && document.activeElement.id === "ticket-reply-text") {
            return;
        }

        box.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:12px">
                <div>
                    <h3 style="margin:0">Ticket #${t.id} · ${escape(t.category || "")} · <span class="pill ${t.status === 'closed' ? 'st-fail' : 'st-ok'}">${t.status}</span></h3>
                    <p class="sub" style="margin:4px 0 0">${escape(t.opener_name || "")} · abierto ${(t.created_at || "").replace("T"," ").slice(0,16)} · <a href="${webLink}">enlace directo</a></p>
                </div>
                <a href="${transcriptUrl}" target="_blank" class="btn btn-ghost btn-sm"><i class="fas fa-file-lines"></i> Transcript Completo</a>
            </div>
            ${lines}
            ${actionFooter}
        `;
    } catch (e) {
        if (!silent && box) box.innerHTML = `<p class="empty">${t("dash.empty.open_fail")}</p>`;
    }
}

async function sendTicketReply(ticketId) {
    const area = document.getElementById("ticket-reply-text");
    if (!area) return;
    const msg = area.value.trim();
    if (!msg) return toast("Escribe un mensaje antes de enviar", "warning");
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/tickets/${ticketId}/reply`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ content: msg })
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || "Error al enviar");
        toast("Respuesta sincronizada con Discord", "success");
        area.value = "";
        await openTicket(ticketId, false);
    } catch (e) {
        toast(e.message || "Error al enviar", "error");
    }
}

async function closeCurrentTicket(ticketId) {
    if (!confirm(`¿Confirmas que deseas CERRAR este ticket (#${ticketId})?\nSe enviará el aviso a Discord y se registrará el cierre en la base de datos.`)) return;
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/tickets/${ticketId}/close`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({})
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || "Error al cerrar");
        toast("Ticket cerrado con éxito", "success");
        await openTicket(ticketId, false);
        loadTickets();
    } catch (e) {
        toast(e.message || "Error al cerrar ticket", "error");
    }
}

async function quickGuildPremium(guildId, grant) {
    const payload = {
        guild_id: String(guildId),
        action: grant ? "grant" : "revoke",
        plan: "lifetime",
        duration_days: 30
    };
    const res = await fetch("/api/admin/premium/guild", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return toast(data.detail || "No se pudo cambiar Premium", "error");
    toast(data.message || (grant ? "Premium activado" : "Premium quitado"), "success");
    loadAdminDiagnostics();
    loadAdminBotGuilds();
}

let liveState = { guildId: null, channelId: null, after: null, timer: null, sending: false, gen: 0 };

function fillLiveGuildSelect(guilds) {
    const sel = $("live-guild");
    if (!sel) return;
    const current = liveState.guildId || sel.value;
    sel.innerHTML = `<option value="">Elige servidor…</option>` + (guilds || []).map(g =>
        `<option value="${g.id}">${esc(g.name || g.id)}</option>`
    ).join("");
    if (current && [...sel.options].some(o => o.value === current)) sel.value = current;
}

function liveAvatar(author) {
    if (author && author.id && author.avatar) {
        return `https://cdn.discordapp.com/avatars/${author.id}/${author.avatar}.png?size=64`;
    }
    return "https://cdn.discordapp.com/embed/avatars/0.png";
}

function renderLiveMessage(m) {
    const when = m.timestamp ? new Date(m.timestamp).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }) : "";
    const atts = (m.attachments || []).map(a => {
        const url = (a.url || "").replace(/"/g, "");
        const isImg = (a.content_type || "").startsWith("image/") || /\.(png|jpe?g|gif|webp)(\?|$)/i.test(url);
        return isImg ? `<img class="att" src="${esc(url)}" alt="">` : `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(a.filename || "archivo")}</a>`;
    }).join("");
    return `<div class="live-msg" data-id="${esc(m.id)}">
        <img class="av" src="${esc(liveAvatar(m.author))}" alt="">
        <div>
            <div><span class="who">${esc((m.author && m.author.username) || "Usuario")}</span>${m.author && m.author.bot ? '<span class="bot">BOT</span>' : ""}<span class="when">${esc(when)}</span></div>
            <div class="body">${esc(m.content || "")}</div>
            ${atts}
        </div>
    </div>`;
}

function stopLivePoll() {
    liveState.gen = (liveState.gen || 0) + 1;
    if (liveState.timer) {
        clearInterval(liveState.timer);
        liveState.timer = null;
    }
}

async function liveSelectGuild(guildId) {
    stopLivePoll();
    liveState.guildId = guildId || null;
    liveState.channelId = null;
    liveState.after = null;
    const sel = $("live-guild");
    if (sel && guildId) sel.value = guildId;
    const box = $("live-channels");
    const msgs = $("live-messages");
    if ($("live-input")) $("live-input").disabled = true;
    if ($("live-send-btn")) $("live-send-btn").disabled = true;
    if ($("live-channel-title")) $("live-channel-title").innerText = "Ningún canal";
    if ($("live-channel-sub")) $("live-channel-sub").innerText = "Elige un canal";
    if (msgs) msgs.innerHTML = `<div class="empty">Selecciona un canal a la izquierda</div>`;
    if (!guildId) {
        if (box) box.innerHTML = `<div class="empty">Elige un servidor</div>`;
        return;
    }
    if (box) box.innerHTML = `<div class="empty">Cargando canales…</div>`;
    try {
        const res = await fetch(`/api/admin/live/guilds/${guildId}/channels`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (box) box.innerHTML = `<div class="empty">${esc(data.detail || "No se pudieron cargar los canales. Espera unos segundos y reintenta.")}</div>`;
            return;
        }
        const channels = data.channels || [];
        if (!channels.length) {
            if (box) box.innerHTML = `<div class="empty">No hay canales de texto (o Discord no los listó). Reintenta en 10 s.</div>`;
            return;
        }
        let html = "";
        let lastCat = "__none__";
        channels.forEach(ch => {
            const cat = ch.category || "Canales";
            if (cat !== lastCat) {
                html += `<div class="live-cat">${esc(cat)}</div>`;
                lastCat = cat;
            }
            html += `<button type="button" class="live-ch" data-id="${ch.id}" data-name="${esc(ch.name)}" onclick="liveSelectChannel(this)"># ${esc(ch.name)}</button>`;
        });
        if (box) box.innerHTML = html;
        const panel = document.getElementById("view-admin");
        if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
        if (box) box.innerHTML = `<div class="empty">No se pudieron cargar los canales</div>`;
    }
}

async function liveSelectChannel(btnOrId, name) {
    const channelId = (btnOrId && btnOrId.dataset) ? btnOrId.dataset.id : btnOrId;
    name = (btnOrId && btnOrId.dataset) ? (btnOrId.dataset.name || name) : name;
    stopLivePoll();
    liveState.channelId = channelId;
    liveState.after = null;
    document.querySelectorAll(".live-ch").forEach(btn => btn.classList.toggle("active", btn.dataset.id === String(channelId)));
    if ($("live-channel-title")) $("live-channel-title").innerText = `# ${name || channelId}`;
    if ($("live-channel-sub")) $("live-channel-sub").innerText = "En vivo · se actualiza solo";
    if ($("live-input")) { $("live-input").disabled = false; $("live-input").focus(); }
    if ($("live-send-btn")) $("live-send-btn").disabled = false;
    fetch(`/api/admin/live/watch/${channelId}`, { method: "POST" }).catch(() => {});
    await liveLoadMessages(true);
    const gen = liveState.gen;
    liveState.timer = setInterval(() => {
        if (liveState.gen !== gen) return;
        if (document.hidden) return;
        liveLoadMessages(false);
    }, 2000);
}

async function liveLoadMessages(reset) {
    if (!liveState.channelId) return;
    const box = $("live-messages");
    if (!box) return;
    try {
        const q = liveState.after && !reset ? `?after=${encodeURIComponent(liveState.after)}` : "";
        const data = await (await fetch(`/api/admin/live/channels/${liveState.channelId}/messages${q}`)).json();
        const messages = data.messages || [];
        if (reset) {
            box.innerHTML = messages.length ? messages.map(renderLiveMessage).join("") : `<div class="empty">No hay mensajes recientes</div>`;
            box.scrollTop = box.scrollHeight;
        } else if (messages.length) {
            const empty = box.querySelector(".empty");
            if (empty) empty.remove();
            messages.forEach(m => {
                if (!box.querySelector(`[data-id="${m.id}"]`)) box.insertAdjacentHTML("beforeend", renderLiveMessage(m));
            });
            const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
            if (nearBottom) box.scrollTop = box.scrollHeight;
        }
        if (messages.length) liveState.after = messages[messages.length - 1].id;
    } catch (e) {
        if (reset) box.innerHTML = `<div class="empty">No se pudieron leer los mensajes</div>`;
    }
}

async function liveSend(ev) {
    if (ev) ev.preventDefault();
    if (!liveState.channelId || liveState.sending) return;
    const input = $("live-input");
    const content = (input && input.value || "").trim();
    if (!content) return;
    liveState.sending = true;
    try {
        const res = await fetch(`/api/admin/live/channels/${liveState.channelId}/messages`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "No se pudo enviar");
        if (input) input.value = "";
        const box = $("live-messages");
        if (box && data.message) {
            const empty = box.querySelector(".empty");
            if (empty) empty.remove();
            if (!box.querySelector(`[data-id="${data.message.id}"]`)) box.insertAdjacentHTML("beforeend", renderLiveMessage(data.message));
            box.scrollTop = box.scrollHeight;
            liveState.after = data.message.id;
        }
        setTimeout(() => liveLoadMessages(false), 800);
    } catch (e) {
        toast(e.message || "No se pudo enviar", "error");
    } finally {
        liveState.sending = false;
    }
}

async function submitAdminGrant() {
    const targetType = document.getElementById("adm-target-type").value;
    const targetId = document.getElementById("adm-target-id").value;
    const action = document.getElementById("adm-target-action").value;
    const durationDays = parseInt(document.getElementById("adm-target-days").value) || 30;
    const plan = ($("adm-target-plan") && $("adm-target-plan").value) || "monthly";
    if (!targetId) return toast("ID inválido", "warning");
    const payload = { action, duration_days: durationDays, plan };
    if (targetType === "user") payload.user_id = String(targetId).trim();
    else payload.guild_id = String(targetId).trim();
    const res = await fetch(`/api/admin/premium/${targetType}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const data = await res.json();
    toast(data.message || "Hecho", data.status === "success" ? "success" : "error");
    loadAdminDiagnostics();
    loadAdminBotGuilds();
}

function downloadDbBackup() { window.open("/api/admin/backup/download", "_blank"); }

async function loadGuildBackupInfo() {
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/backup`);
        if (!res.ok) return;
        const data = await res.json();
        const gate = document.getElementById("backup-premium-gate");
        const controls = document.getElementById("backup-controls");
        const statusText = document.getElementById("backup-status-text");
        const btnRestore = document.getElementById("btn-restore-backup");
        if (data.is_premium) {
            gate.classList.add("hidden");
            controls.classList.remove("hidden");
            if (data.status === "running") {
                statusText.innerHTML = t("dash.backup.in_progress");
                btnRestore.disabled = true;
            } else if (data.has_backup) {
                const kind = data.kind === "full" ? "completa (mensajes + archivos)" : "estructura";
                statusText.innerHTML = t("dash.backup.last", {kind, when: new Date(data.created_at).toLocaleString()});
                btnRestore.disabled = false;
                if (data.backups && data.backups[0]) {
                    const id = data.backups[0].id;
                    statusText.innerHTML += ` · <a href="/api/guilds/${currentGuildId}/backup/${id}/download">descargar zip</a>`;
                }
            } else {
                statusText.innerHTML = t("dash.backup.none");
                btnRestore.disabled = true;
            }
        } else {
            gate.classList.remove("hidden");
            controls.classList.add("hidden");
        }
    } catch (e) { console.error(e); }
}

async function createGuildBackup() {
    showLoading();
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/backup/create`, { method: "POST" });
        hideLoading();
        const err = res.ok ? null : await res.json();
        toast(res.ok ? "Backup creado" : (err.detail || "Error"), res.ok ? "success" : "error");
        if (res.ok) loadGuildBackupInfo();
    } catch {
        hideLoading();
        toast("Error de red", "error");
    }
}

async function restoreGuildBackup() {
    const confirmation = await Swal.fire({
        title: t("dash.restore_title"),
        text: t("dash.restore_text"),
        icon: "warning", showCancelButton: true, confirmButtonColor: "#fb7185",
        background: "#111a30", color: "#fff"
    });
    if (!confirmation.isConfirmed) return;
    showLoading();
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/backup/restore`, { method: "POST" });
        hideLoading();
        toast(res.ok ? t("dash.restore_started") : t("toast.error"), res.ok ? "success" : "error");
    } catch {
        hideLoading();
        toast("Error de red", "error");
    }
}

async function loadAudit() {
    const tbody = $("audit-table-body");
    if (!tbody || !currentGuildId) return;
    const type = ($("audit-filter") && $("audit-filter").value) || "";
    tbody.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.loading")}</td></tr>`;
    try {
        const url = `/api/guilds/${currentGuildId}/audit?limit=80` + (type ? `&type=${encodeURIComponent(type)}` : "");
        const data = await (await fetch(url)).json();
        const events = data.events || [];
        await resolveUsers(events.flatMap(e => [e.actor_id, e.target_id].filter(Boolean)));
        if (!events.length) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.logs")}</td></tr>`;
            return;
        }
        tbody.innerHTML = events.map(e => `<tr>
            <td>${e.timestamp ? new Date(e.timestamp).toLocaleString() : ""}</td>
            <td><span class="pill">${e.type}</span></td>
            <td>${(e.summary || "").replace(/</g, "")}</td>
            <td>${e.actor_id ? userCell(e.actor_id) : "—"}</td>
            <td>${e.target_id ? userCell(e.target_id) : "—"}</td>
        </tr>`).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty">No se pudieron leer los registros.</td></tr>`;
    }
}

let templateLang = (localStorage.getItem("dabot_lang") || "es").startsWith("en") ? "en" : "es";

function setTemplateLang(lang) {
    templateLang = lang === "en" ? "en" : "es";
    loadTemplates();
}

async function loadTemplates() {
    const grid = $("templates-grid");
    if (!grid) return;
    grid.innerHTML = `<div class="empty">${t("dash.empty.templates")}</div>`;
    const esBtn = $("tpl-lang-es");
    const enBtn = $("tpl-lang-en");
    if (esBtn) esBtn.classList.toggle("active", templateLang === "es");
    if (enBtn) enBtn.classList.toggle("active", templateLang === "en");
    try {
        const data = await (await fetch(`/api/templates?lang=${templateLang}`)).json();
        grid.innerHTML = "";
        (data.templates || []).forEach(t => {
            const card = document.createElement("div");
            card.className = "server-card glass";
            const safeName = (t.name || "").replace(/'/g, "").replace(/</g, "");
            card.innerHTML = `<div style="font-size:2rem">${t.icon}</div>
                <h3>${safeName}</h3>
                <p class="sub" style="margin:0">${(t.description || "").replace(/</g, "")}</p>
                <div class="pill">${t.roles} roles · ${t.channels} canales</div>
                <button class="btn btn-primary btn-block btn-sm" onclick="applyTemplate('${t.id}', '${safeName}')">Aplicar</button>`;
            grid.appendChild(card);
        });
    } catch (e) {
        grid.innerHTML = `<div class="empty">No se pudieron cargar las plantillas.</div>`;
    }
}

async function applyTemplate(id, name) {
    const { isConfirmed } = await Swal.fire({
        title: t("dash.template.apply_title", {name}),
        text: templateLang === "en"
            ? "This WIPES current channels and roles, then builds logs, verification, welcome, rules and tickets from the template."
            : t("dash.template.apply_text"),
        icon: "question",
        showCancelButton: true,
        confirmButtonColor: "#00ff88",
        background: "#111a30",
        color: "#fff"
    });
    if (!isConfirmed) return;
    showLoading();
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/templates/apply`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ template_id: id, lang: templateLang })
        });
        hideLoading();
        const data = await res.json();
        toast(data.message || (res.ok ? "Plantilla en marcha" : "Error"), res.ok ? "success" : "error");
    } catch {
        hideLoading();
        toast("Error de red", "error");
    }
}

async function nukeGuild() {
    const g = guildsCache[currentGuildId] || {};
    const name = g.name || "";
    const { value } = await Swal.fire({
        title: t("dash.nuke_title"),
        html: `Se borran <b>todos</b> los canales y roles de <b>${(name || "").replace(/</g, "")}</b>.<br>Escribe el nombre exacto para confirmar.`,
        input: "text",
        inputPlaceholder: name,
        showCancelButton: true,
        confirmButtonColor: "#fb7185",
        background: "#111a30",
        color: "#fff",
        icon: "warning"
    });
    if (value == null) return;
    showLoading();
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/nuke`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirm_name: value })
        });
        hideLoading();
        const data = await res.json().catch(() => ({}));
        toast(res.ok ? (data.message || "Nuke en marcha") : (data.detail || "No autorizado"), res.ok ? "success" : "error");
    } catch {
        hideLoading();
        toast("Error de red", "error");
    }
}

function switchDiscord(pane) {
    ["server", "channels", "roles", "members", "rules"].forEach(p => {
        const el = $("d-pane-" + p);
        const btn = $("d-nav-" + p);
        if (el) el.classList.toggle("hidden", p !== pane);
        if (btn) btn.classList.toggle("active", p === pane);
    });
    if (pane === "channels") renderChannels();
    if (pane === "roles") renderRoles();
    if (pane === "members") loadMembers();
}

async function loadDiscord() {
    if (!currentGuildId) return;
    try {
        const g = await (await fetch(`/api/guilds/${currentGuildId}/discord`)).json();
        if ($("d-guild-name")) $("d-guild-name").value = g.name || "";
        if ($("d-guild-verify")) $("d-guild-verify").value = String(g.verification_level ?? 0);
        if ($("d-guild-notif")) $("d-guild-notif").value = String(g.default_message_notifications ?? 1);
        if ($("d-rules")) $("d-rules").value = g.rules || "";
        if ($("d-guild-meta")) $("d-guild-meta").innerText = `${g.member_count || "?"} miembros · boost nivel ${g.premium_tier || 0}`;
        const chans = await (await fetch(`/api/guilds/${currentGuildId}/channels`)).json();
        serverChannels = Array.isArray(chans) ? chans : [];
        const roles = await (await fetch(`/api/guilds/${currentGuildId}/roles`)).json();
        window._roles = Array.isArray(roles) ? roles : [];
        switchDiscord("server");
    } catch (e) { console.error(e); }
}

async function saveGuildDiscord() {
    const res = await fetch(`/api/guilds/${currentGuildId}/discord`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name: $("d-guild-name").value,
            verification_level: parseInt($("d-guild-verify").value),
            default_message_notifications: parseInt($("d-guild-notif").value),
            rules: $("d-rules").value
        })
    });
    toast(res.ok ? "Servidor actualizado" : t("dash.save_perm_error"), res.ok ? "success" : "error");
}

function renderChannels() {
    const box = $("d-ch-list");
    if (!box) return;
    const cats = serverChannels.filter(c => c.type === 4);
    const texts = serverChannels.filter(c => c.type === 0 || c.type === 5 || c.type === 2);
    box.innerHTML = texts.map(c => {
        const kind = c.type === 2 ? "voz" : (c.type === 4 ? "cat" : "texto");
        return `<div class="switch-row">
            <div><b># ${htmlEscape(c.name)}</b> <span class="pill">${kind}</span></div>
            <div class="mini-actions">
                <button class="btn btn-ghost btn-sm" onclick="editChannel('${htmlEscape(c.id)}')">Editar</button>
                <button class="btn btn-danger btn-sm" onclick="deleteChannel('${htmlEscape(c.id)}')">Borrar</button>
            </div>
        </div>`;
    }).join("") || `<div class="empty">${t("dash.empty.channels")}</div>`;
}

async function createChannel() {
    const name = $("d-ch-name").value;
    const type = parseInt($("d-ch-type").value);
    if (!name) return toast("Pon un nombre", "warning");
    const res = await fetch(`/api/guilds/${currentGuildId}/channels`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, type })
    });
    toast(res.ok ? "Canal creado" : "Error al crear", res.ok ? "success" : "error");
    if (res.ok) {
        serverChannels = await (await fetch(`/api/guilds/${currentGuildId}/channels`)).json();
        renderChannels();
    }
}

async function editChannel(id, name, topic) {
    const ch = (serverChannels || []).find(c => String(c.id) === String(id)) || {};
    name = name || ch.name || "";
    topic = topic || ch.topic || "";
    const slowmode = ch.rate_limit_per_user || 0;

    const { value } = await Swal.fire({
        title: "Editar canal",
        html: `<input id="sw-n" class="swal2-input" value="${htmlEscape(name)}"><textarea id="sw-t" class="swal2-textarea" placeholder="Tema">${htmlEscape(topic)}</textarea>
               <input id="sw-s" class="swal2-input" type="number" placeholder="Slowmode segundos" value="${slowmode}">`,
        background: "#111a30", color: "#fff", confirmButtonColor: "#00ff88",
        preConfirm: () => ({
            name: document.getElementById("sw-n").value,
            topic: document.getElementById("sw-t").value,
            rate_limit_per_user: parseInt(document.getElementById("sw-s").value) || 0
        })
    });
    if (!value) return;
    const res = await fetch(`/api/channels/${id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value)
    });
    toast(res.ok ? "Canal actualizado" : "Error", res.ok ? "success" : "error");
}

async function deleteChannel(id) {
    const { isConfirmed } = await Swal.fire({ title: t("dash.delete_channel_title"), icon: "warning", showCancelButton: true, background: "#111a30", color: "#fff", confirmButtonColor: "#fb7185" });
    if (!isConfirmed) return;
    const res = await fetch(`/api/channels/${id}`, { method: "DELETE" });
    toast(res.ok ? "Canal borrado" : "Error", res.ok ? "success" : "error");
    if (res.ok) {
        serverChannels = await (await fetch(`/api/guilds/${currentGuildId}/channels`)).json();
        renderChannels();
    }
}

function renderRoles() {
    const box = $("d-role-list");
    if (!box) return;
    const roles = window._roles || [];
    box.innerHTML = roles.map(r => `<div class="switch-row">
        <div><b style="color:${r.color ? '#' + r.color.toString(16).padStart(6,'0') : '#fff'}">${r.name}</b></div>
        <button class="btn btn-danger btn-sm" onclick="deleteRole('${r.id}')">Borrar</button>
    </div>`).join("") || '<div class="empty">Sin roles.</div>';
}

async function createRole() {
    const name = $("d-role-name").value;
    const hex = ($("d-role-color").value || "#00ff88").replace("#", "");
    if (!name) return toast("Nombre del rol", "warning");
    const res = await fetch(`/api/guilds/${currentGuildId}/roles`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, color: parseInt(hex, 16), hoist: true })
    });
    toast(res.ok ? "Rol creado" : "Error", res.ok ? "success" : "error");
    if (res.ok) {
        window._roles = await (await fetch(`/api/guilds/${currentGuildId}/roles`)).json();
        renderRoles();
    }
}

async function deleteRole(id) {
    const res = await fetch(`/api/guilds/${currentGuildId}/roles/${id}`, { method: "DELETE" });
    toast(res.ok ? "Rol borrado" : "Error", res.ok ? "success" : "error");
    if (res.ok) {
        window._roles = await (await fetch(`/api/guilds/${currentGuildId}/roles`)).json();
        renderRoles();
    }
}

async function loadMembers() {
    const box = $("d-member-list");
    if (!box) return;
    const q = ($("d-member-q") && $("d-member-q").value) || "";
    box.innerHTML = t("dash.empty.loading");
    try {
        const data = await (await fetch(`/api/guilds/${currentGuildId}/members?q=${encodeURIComponent(q)}`)).json();
        const members = data.members || [];
        box.innerHTML = members.map(m => {
            const av = m.avatar ? `https://cdn.discordapp.com/avatars/${m.id}/${m.avatar}.png` : "https://cdn.discordapp.com/embed/avatars/0.png";
            const name = m.nick || m.global_name || m.username;
            return `<div class="switch-row">
                <div class="user-cell"><img src="${av}" alt=""><div><b>${name}</b><div class="mono">${m.username}</div></div></div>
                <div class="mini-actions">
                    <button class="btn btn-ghost btn-sm" onclick="memberAction('${m.id}','nick')">Nick</button>
                    <button class="btn btn-ghost btn-sm" onclick="memberAction('${m.id}','timeout')">Timeout</button>
                    <button class="btn btn-danger btn-sm" onclick="memberAction('${m.id}','kick')">Kick</button>
                    <button class="btn btn-danger btn-sm" onclick="memberAction('${m.id}','ban')">Ban</button>
                </div>
            </div>`;
        }).join("") || '<div class="empty">Sin resultados. Prueba a buscar un nick.</div>';
    } catch {
        box.innerHTML = '<div class="empty">No se pudieron listar miembros (intents / permisos).</div>';
    }
}

async function memberAction(id, kind) {
    if (kind === "nick") {
        const { value } = await Swal.fire({ title: "Nuevo nick", input: "text", background: "#111a30", color: "#fff", confirmButtonColor: "#00ff88" });
        if (value == null) return;
        const res = await fetch(`/api/guilds/${currentGuildId}/members/${id}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nick: value })
        });
        toast(res.ok ? "Nick cambiado" : "Error", res.ok ? "success" : "error");
        return;
    }
    if (kind === "timeout") {
        const { value } = await Swal.fire({ title: "Minutos de timeout", input: "number", inputValue: 10, background: "#111a30", color: "#fff", confirmButtonColor: "#a855f7" });
        if (!value) return;
        const res = await fetch(`/api/guilds/${currentGuildId}/members/${id}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ timeout_minutes: parseInt(value), reason: "Timeout desde el panel" })
        });
        toast(res.ok ? "Timeout aplicado" : "Error", res.ok ? "success" : "error");
        return;
    }
    const { value: reason } = await Swal.fire({ title: kind === "ban" ? "Banear" : "Expulsar", input: "text", inputPlaceholder: "Motivo", background: "#111a30", color: "#fff", confirmButtonColor: "#fb7185" });
    if (reason === undefined) return;
    let res;
    if (kind === "kick") {
        res = await fetch(`/api/guilds/${currentGuildId}/members/${id}`, {
            method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason || "Kick desde el panel" })
        });
    } else {
        res = await fetch(`/api/guilds/${currentGuildId}/bans/${id}`, {
            method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason || "Ban desde el panel" })
        });
    }
    toast(res.ok ? "Hecho" : t("dash.role_hierarchy_error"), res.ok ? "success" : "error");
}

async function toggleAltShare(guildId, enabled) {
    const res = await fetch("/api/admin/alt-network", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ guild_id: parseInt(guildId, 10), enabled })
    });
    toast(res.ok ? (enabled ? t("dash.alt_share_on") : t("dash.alt_share_off")) : t("dash.change_fail"), res.ok ? "success" : "error");
}

const ALT_REASON = {
    misma_ip: "Misma IP",
    misma_red: "Misma red /24",
    mismo_dispositivo: "Mismo dispositivo (cookie)",
    mismo_navegador: "Misma huella de navegador",
    mismo_nombre: "Mismo nombre"
};

const ALT_STATUS = {
    pending: "Pendiente",
    approved: "Aprobado",
    denied: "Denegado",
    banned: "Baneado",
    allow_always: "Siempre"
};

function riskPill(c) {
    const label = (c.risk || "low").toLowerCase();
    return `<span class="pill risk-${label}">${c.score || 0} · ${label}</span>`;
}

function statusPill(status) {
    const st = status || "pending";
    return `<span class="pill st-${st}">${ALT_STATUS[st] || st}</span>`;
}

function caseActionsHtml(c, admin) {
    if (c.status !== "pending") return statusPill(c.status);
    const flag = admin ? "true" : "false";
    return `<div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" onclick="resolveAltCase(${c.id},'ok',${flag})">Aprobar</button>
        <button class="btn btn-ghost btn-sm" onclick="resolveAltCase(${c.id},'no',${flag})">Denegar</button>
        <button class="btn btn-danger btn-sm" onclick="resolveAltCase(${c.id},'ban',${flag})">Banear</button>
        <button class="btn btn-ghost btn-sm" onclick="resolveAltCase(${c.id},'always',${flag})">Siempre</button>
    </div>`;
}

function matchesSummary(c) {
    const n = (c.matches || []).length;
    if (!n) return "—";
    return `${n} cuenta${n === 1 ? "" : "s"}`;
}

function sightingCell(c) {
    const s = c.last_sighting || {};
    const ev = c.evidence || {};
    const codes = [s.ip_code || ev.ip_code, s.net_code || ev.net_code].filter(Boolean).join(" · ");
    const raw = s.ip && !String(s.ip).startsWith("ip:") && !String(s.ip).startsWith("net:") ? String(s.ip) : "";
    const shown = raw ? `${raw}${codes ? " · " + codes : ""}` : (codes || "—");
    const dev = s.device_id ? ` · ${s.device_id}` : "";
    return `<span class="mono">${String(shown).replace(/</g, "")}${dev}</span>`;
}

async function resolveAltCase(caseId, action, admin) {
    const labels = { ok: "Aprobar", no: "Denegar", ban: "Banear", always: "Permitir siempre multicuentas" };
    const { isConfirmed } = await Swal.fire({
        title: labels[action] || action,
        text: `Caso #${caseId}`,
        icon: action === "ban" ? "warning" : "question",
        showCancelButton: true,
        confirmButtonColor: action === "ban" ? "#fb7185" : "#00ff88",
        background: "#111a30",
        color: "#fff"
    });
    if (!isConfirmed) return;
    const url = admin
        ? `/api/admin/alts/cases/${caseId}`
        : `/api/guilds/${currentGuildId}/alts/cases/${caseId}`;
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action })
        });
        const data = await res.json().catch(() => ({}));
        toast(data.message || data.detail || (res.ok ? "Hecho" : "Error"), res.ok ? "success" : "error");
        if (admin) {
            loadAdminAlts();
            loadAdminDiagnostics();
            loadAdminBotGuilds();
        } else {
            loadAlts();
        }
    } catch (e) {
        toast("Error de red", "error");
    }
}

async function loadAlts() {
    if (!currentGuildId) return;
    try {
        const q = ($("alts-query") && $("alts-query").value.trim()) || "";
        const url = `/api/guilds/${currentGuildId}/alts` + (q ? `?q=${encodeURIComponent(q)}` : "");
        const data = await (await fetch(url)).json();
        const scope = $("alts-scope");
        if (scope) scope.innerText = data.network ? t("dash.alts.scope.net") : t("dash.alts.scope");
        const casesBody = $("alts-cases-body");
        if (casesBody) {
            const cases = data.cases || [];
            casesBody.innerHTML = cases.length ? cases.map(c => `<tr>
                <td class="mono">#${c.id}</td>
                <td class="mono"><a href="#" onclick="event.preventDefault();lookupAlt('${c.user_id}')">${c.username || c.user_id}</a><div class="mono">${c.user_id}</div></td>
                <td>${riskPill(c)} <span class="mono">${matchesSummary(c)}</span></td>
                <td>${statusPill(c.status)}<div class="mono">${(c.created_at || "").replace("T"," ").slice(0,16)}</div></td>
                <td>${caseActionsHtml(c, false)}</td>
            </tr>`).join("") : `<tr><td colspan="5" class="empty">${t("dash.empty.alt_cases")}</td></tr>`;
        }
        const body = $("alts-alerts-body");
        if (body) {
            const rows = data.alerts || [];
            body.innerHTML = rows.length ? rows.map(a => `<tr>
                <td class="mono"><a href="#" onclick="event.preventDefault();lookupAlt('${a.user_a}')">${a.user_a}</a> · <a href="#" onclick="event.preventDefault();lookupAlt('${a.user_b}')">${a.user_b}</a></td>
                <td>${ALT_REASON[a.reason] || a.reason}</td>
                <td>${a.score}</td>
                <td>${(a.created_at || "").replace("T", " ").slice(0, 16)}</td>
            </tr>`).join("") : `<tr><td colspan="4" class="empty">${t("dash.empty.alt_hits")}</td></tr>`;
        }
        if (data.dossier) renderDossier(data.dossier, "alts-dossier");
    } catch (e) {
        console.error(e);
    }
}

async function loadAdminAlts() {
    const body = $("adm-alts-body");
    if (body) body.innerHTML = `<tr><td colspan="7" class="empty">${t("dash.empty.loading")}</td></tr>`;
    try {
        const status = ($("adm-alts-status") && $("adm-alts-status").value) || "";
        const q = ($("adm-alts-query") && $("adm-alts-query").value.trim()) || "";
        const params = new URLSearchParams();
        if (status) params.set("status", status);
        if (q) params.set("q", q);
        const data = await (await fetch("/api/admin/alts?" + params.toString())).json();
        const cases = data.cases || [];
        if (body) {
            body.innerHTML = cases.length ? cases.map(c => `<tr>
                <td class="mono">#${c.id}<div class="mono">${(c.created_at || "").replace("T"," ").slice(0,16)}</div></td>
                <td><a href="#" onclick="event.preventDefault();openAdminGuild('${c.guild_id}')">${(c.guild_name || c.guild_id || "").replace(/</g,"")}</a><div class="mono">${c.guild_id || ""}</div></td>
                <td class="mono"><a href="#" onclick="event.preventDefault();adminLookupAlt('${c.user_id}')">${(c.username || c.user_id || "").replace(/</g,"")}</a><div class="mono">${c.user_id}</div><div class="mono">${matchesSummary(c)}</div></td>
                <td>${riskPill(c)}</td>
                <td>${sightingCell(c)}</td>
                <td>${statusPill(c.status)}</td>
                <td>${caseActionsHtml(c, true)}</td>
            </tr>`).join("") : `<tr><td colspan="7" class="empty">${status === "pending" ? t("dash.empty.pending_none") : t("dash.empty.filter_none")}</td></tr>`;
        }
        if (data.dossier) renderDossier(data.dossier, "adm-alts-dossier", true);
        else if ($("adm-alts-dossier") && !q) $("adm-alts-dossier").innerHTML = "";
    } catch (e) {
        console.error(e);
        if (body) body.innerHTML = `<tr><td colspan="7" class="empty">${t("dash.empty.cases_fail")}</td></tr>`;
    }
}

function adminLookupAlt(id) {
    if ($("adm-alts-query")) $("adm-alts-query").value = id;
    loadAdminAlts();
}

function lookupAlt(id) {
    if ($("alts-query")) $("alts-query").value = id;
    searchAlts();
}

async function searchAlts() {
    return loadAlts();
}

const VERIFY_METHOD = {
    web: "Navegador",
    emoji: "Emoji",
    math: "Mates",
    manual: "Staff",
    alt_approve: "Multicuenta"
};
const VERIFY_STATUS = {
    ok: "Verificado",
    already: "Ya estaba",
    pending: "Pendiente",
    fail: "Fallido",
    manual: "Manual",
    denied: "Denegado",
    vpn: "VPN / proxy"
};

function verifyStatusPill(st) {
    const s = st || "ok";
    return `<span class="pill st-${s}">${VERIFY_STATUS[s] || s}</span>`;
}

function verifyUserCell(row, admin) {
    const name = String(row.username || row.user_id || "").replace(/</g, "");
    const av = row.avatar_url || "";
    const img = av.startsWith("http") ? `<img src="${av.replace(/"/g, "")}" alt="">` : "";
    const uid = String(row.user_id || "");
    const fn = admin ? "adminLookupVerify" : "lookupVerify";
    return `<div class="user-cell">${img}<span><a href="#" onclick="event.preventDefault();${fn}('${uid}')">${name || uid}</a><div class="mono">${uid}</div></span></div>`;
}

function verifyRiskCell(row) {
    if (row.risk_score === null || row.risk_score === undefined || row.risk_score === "") return "—";
    const label = row.risk_label || "";
    return `<span class="pill risk-${label || "low"}">${row.risk_score}/100 ${label}</span>`;
}

function verifyNetCell(row) {
    const codes = [row.ip_code, row.net_code].filter(Boolean).join(" · ");
    const raw = row.ip && !String(row.ip).startsWith("ip:") && !String(row.ip).startsWith("net:") ? String(row.ip) : "";
    const vpn = row.vpn ? `<div><span class="pill st-vpn">${(row.vpn_kinds || []).join(" · ") || "VPN"}</span></div>` : "";
    if (raw) {
        const country = (row.country || "").replace(/</g, "");
        const isp = (row.isp || "").replace(/</g, "");
        return `<span class="mono">${raw.replace(/</g, "")}${country ? " · " + country : ""}${isp ? "<div>" + isp + "</div>" : ""}<div>${(codes || "").replace(/</g, "")}</div>${vpn}</span>`;
    }
    return `<span class="mono">${(codes || "—").replace(/</g, "")}${vpn}</span>`;
}

function lookupVerify(id) {
    if ($("verify-query")) $("verify-query").value = id;
    loadVerifications();
}

function adminLookupVerify(id) {
    if ($("adm-verify-query")) $("adm-verify-query").value = id;
    loadAdminVerifications();
}

async function loadVerifications() {
    if (!currentGuildId) return;
    const peopleBody = $("verify-people-body");
    const eventsBody = $("verify-events-body");
    if (peopleBody) peopleBody.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.loading")}</td></tr>`;
    if (eventsBody) eventsBody.innerHTML = `<tr><td colspan="6" class="empty">${t("dash.empty.loading")}</td></tr>`;
    try {
        const q = ($("verify-query") && $("verify-query").value.trim()) || "";
        const method = ($("verify-method") && $("verify-method").value) || "";
        const status = ($("verify-status") && $("verify-status").value) || "";
        const params = new URLSearchParams();
        if (q) params.set("q", q);
        if (method) params.set("method", method);
        if (status) params.set("status", status);
        params.set("limit", "150");
        const data = await (await fetch(`/api/guilds/${currentGuildId}/verifications?` + params.toString())).json();
        const stats = data.stats || {};
        const pill = $("verify-stats-pill");
        if (pill) pill.innerText = `${stats.people || 0} personas · ${stats.events || 0} eventos · ${stats.today || 0} hoy`;
        const people = data.people || [];
        if (peopleBody) {
            peopleBody.innerHTML = people.length ? people.map(p => `<tr>
                <td>${verifyUserCell(p)}</td>
                <td>${VERIFY_METHOD[p.method] || p.method || "—"}</td>
                <td>${verifyRiskCell(p)}</td>
                <td>${verifyNetCell(p)}</td>
                <td class="mono">${(p.created_at || "").replace("T", " ").slice(0, 16)}</td>
            </tr>`).join("") : `<tr><td colspan="5" class="empty">${t("dash.empty.nobody_verified")}</td></tr>`;
        }
        const events = data.events || [];
        if (eventsBody) {
            eventsBody.innerHTML = events.length ? events.map(e => `<tr>
                <td class="mono">#${e.id}</td>
                <td>${verifyUserCell(e)}</td>
                <td>${VERIFY_METHOD[e.method] || e.method || "—"}</td>
                <td>${verifyStatusPill(e.status)}</td>
                <td>${verifyNetCell(e)}</td>
                <td class="mono">${(e.created_at || "").replace("T", " ").slice(0, 16)}</td>
            </tr>`).join("") : `<tr><td colspan="6" class="empty">${t("dash.empty.no_events")}</td></tr>`;
        }
    } catch (e) {
        console.error(e);
        if (peopleBody) peopleBody.innerHTML = `<tr><td colspan="5" class="empty">${t("dash.empty.list_fail")}</td></tr>`;
        if (eventsBody) eventsBody.innerHTML = `<tr><td colspan="6" class="empty">${t("dash.empty.history_fail")}</td></tr>`;
    }
}

async function loadAdminVerifications() {
    const body = $("adm-verify-body");
    if (!body) return;
    body.innerHTML = `<tr><td colspan="7" class="empty">${t("dash.empty.loading")}</td></tr>`;
    try {
        const status = ($("adm-verify-status") && $("adm-verify-status").value) || "";
        const method = ($("adm-verify-method") && $("adm-verify-method").value) || "";
        const q = ($("adm-verify-query") && $("adm-verify-query").value.trim()) || "";
        const params = new URLSearchParams();
        if (status) params.set("status", status);
        if (method) params.set("method", method);
        if (q) params.set("q", q);
        const data = await (await fetch("/api/admin/verifications?" + params.toString())).json();
        const events = data.events || [];
        body.innerHTML = events.length ? events.map(e => `<tr>
            <td class="mono"><a href="#" onclick="event.preventDefault();openAdminVerify(${e.id})">#${e.id}</a></td>
            <td><a href="#" onclick="event.preventDefault();openAdminGuild('${e.guild_id}')">${String(e.guild_name || e.guild_id || "").replace(/</g, "")}</a><div class="mono">${e.guild_id || ""}</div></td>
            <td>${verifyUserCell(e, true)}</td>
            <td>${VERIFY_METHOD[e.method] || e.method || "—"}</td>
            <td>${verifyStatusPill(e.status)}</td>
            <td>${verifyNetCell(e)}</td>
            <td class="mono">${(e.created_at || "").replace("T", " ").slice(0, 16)}</td>
        </tr>`).join("") : `<tr><td colspan="7" class="empty">${t("dash.empty.verifs_filter")}</td></tr>`;
    } catch (e) {
        console.error(e);
        body.innerHTML = `<tr><td colspan="7" class="empty">${t("dash.empty.verifs_fail")}</td></tr>`;
    }
}

function esc(s) {
    return htmlEscape(s);
}

async function openAdminVerify(id) {
    const box = $("adm-verify-detail");
    if (!box) return;
    box.innerHTML = `<p class="sub">${t("dash.empty.loading_id", {id})}</p>`;
    try {
        const e = await (await fetch(`/api/admin/verifications/${id}`)).json();
        if (e.detail && !e.id) {
            box.innerHTML = `<p class="sub">${esc(e.detail)}</p>`;
            return;
        }
        const extra = e.extra || {};
        const proxy = extra.proxy || {};
        const rows = [
            ["#", e.id],
            ["Servidor", `${e.guild_name || ""} · ${e.guild_id || ""}`],
            ["Usuario", `${e.username || ""} · ${e.user_id || ""}`],
            [t("dash.table.method"), e.method || ""],
            ["Estado", e.status || ""],
            [t("dash.raw.when"), (e.created_at || "").replace("T", " ")],
            ["IP completa", e.ip && !String(e.ip).startsWith("ip:") ? e.ip : ""],
            [t("dash.verify.field.exact"), e.ip_code || ""],
            [t("dash.verify.field.net"), e.net_code || ""],
            [t("dash.verify.field.country"), e.country || proxy.cf_country || ""],
            ["Ciudad", e.city || proxy.city || ""],
            ["ISP", e.isp || proxy.isp || ""],
            ["Org", e.org || proxy.org || ""],
            ["ASN", e.asn || proxy.asn || ""],
            [t("dash.verify.vpn_proxy"), (e.vpn || proxy.blocked) ? t("dash.verify.vpn_yes", {kinds: (e.vpn_kinds || proxy.kinds || []).join(", ")}) : t("dash.verify.no")],
            ["Motivos", (e.vpn_reasons || proxy.reasons || []).join(" · ")],
            [t("dash.verify.hosting_flag"), t("dash.verify.hosting_line", {hosting: proxy.hosting ? "hosting" : "—", proxy: proxy.proxy_flag ? "proxy" : "—", mobile: proxy.mobile ? t("dash.verify.yes") : t("dash.verify.no")})],
            ["WebRTC", (proxy.webrtc || []).join(", ")],
            ["Dispositivo", e.device_id || ""],
            ["User-Agent", e.ua || extra.ua || ""],
            ["Timezone", e.timezone || extra.timezone || ""],
            ["Idioma", extra.lang || ""],
            ["Plataforma", e.platform || extra.platform || ""],
            ["Pantalla", e.screen || extra.screen || ""],
            ["Riesgo", e.risk_score != null ? `${e.risk_score}/100 ${e.risk_label || ""}` : "—"],
            ["Caso alt", e.case_id || "—"],
            ["Staff", e.actor_id || "—"],
        ];
        box.innerHTML = `<div class="panel glass" style="margin-top:12px">
            <div class="toolbar" style="margin-bottom:8px">
                <h3 style="margin:0">${t("dash.verify.detail_h", {id: esc(e.id)})}</h3>
                <button class="btn btn-ghost btn-sm" onclick="$('adm-verify-detail').innerHTML=''">Cerrar</button>
            </div>
            <div style="overflow:auto">
                <table>
                    <tbody>${rows.map(([k, v]) => `<tr><th style="width:180px">${esc(k)}</th><td class="mono" style="white-space:normal;word-break:break-word">${esc(v)}</td></tr>`).join("")}</tbody>
                </table>
            </div>
        </div>`;
        box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
        box.innerHTML = `<p class="sub">${t("dash.empty.detail_fail")}</p>`;
    }
}

function renderDossier(d, targetId, admin) {
    const box = $(targetId || "alts-dossier");
    if (!box) return;
    const fn = admin ? "adminLookupAlt" : "lookupAlt";
    const alts = (d.alts || []).map(a => `<li><a href="#" onclick="event.preventDefault();${fn}('${a.user_id}')">${a.user_id}</a> — <b>${a.score}%</b> · ${(a.reasons || []).map(r => ALT_REASON[r] || r).join(", ")}</li>`).join("") || "<li>Ninguna cuenta enlazada.</li>";
    const sights = (d.sightings || []).slice(0, 8).map(s => {
        const codes = [s.ip_code, s.net_code].filter(Boolean).join(" · ");
        const raw = admin && s.ip && !String(s.ip).startsWith("ip:") ? String(s.ip) : "";
        const net = (raw ? raw + (codes ? " · " + codes : "") : (codes || "—")).replace(/</g, "");
        return `<tr>
        <td>${(s.created_at || "").replace("T"," ").slice(0,16)}</td>
        <td>${s.source || ""}</td>
        <td class="mono">${net}${s.country ? " · " + String(s.country).replace(/</g, "") : ""}</td>
        <td>${s.ua_summary || "—"}</td>
        <td class="mono">${s.timezone || ""} ${s.lang || ""}</td>
    </tr>`;
    }).join("") || `<tr><td colspan="5" class="empty">${t("dash.empty.fingerprints")}</td></tr>`;
    box.innerHTML = `
        <p><b>Usuario</b> <span class="mono">${d.user_id}</span> · riesgo ${d.score || 0}%</p>
        <ul>${alts}</ul>
        <div style="overflow:auto">
            <table>
                <thead><tr><th>${t("dash.raw.when")}</th><th>${t("dash.verify.col.origin")}</th><th>${t("dash.verify.col.ip")}</th><th>${t("dash.verify.col.client")}</th><th>${t("dash.verify.col.locale")}</th></tr></thead>
                <tbody>${sights}</tbody>
            </table>
        </div>`;
}

document.addEventListener("dabot:lang", () => {
    if (window.DabotI18n) window.DabotI18n.apply();
    if (currentGuildId) {
        const active = document.querySelector("#guild-nav .nav-btn.active");
        const tab = active && active.id ? active.id.replace("nav-", "") : "overview";
        loadGuildData(currentGuildId, tab);
    } else {
        loadGuildsList();
    }
});

window.onload = loadUser;

async function loadModQueue() {
    const box = $("mod-queue");
    if (!box || !currentGuildId) return;
    try {
        const q = await (await fetch(`/api/guilds/${currentGuildId}/mod-queue`)).json();
        const ids = [
            ...(q.appeals || []).map(a => a.user_id),
            ...(q.tickets || []).map(a => a.user_id),
            ...(q.alts || []).map(a => a.user_id),
            ...(q.hijacks || []).map(a => a.user_id),
        ];
        await resolveUsers(ids);
        const block = (title, rows) => `<div><b>${title}</b><div class="sub">${rows || "Nada pendiente."}</div></div>`;
        const appeals = (q.appeals || []).map(a =>
            `#${a.infraction_id} ${userCell(a.user_id)} · ${esc(a.appeal_reason || "").slice(0, 80)}`
        ).join("<br>");
        const tickets = (q.tickets || []).map(t =>
            `#${t.id} ${userCell(t.user_id)}`
        ).join("<br>");
        const alts = (q.alts || []).map(a =>
            `#${a.id} ${userCell(a.user_id)} · ${esc(a.risk || "")}`
        ).join("<br>");
        const hij = (q.hijacks || []).map(a =>
            `${userCell(a.user_id)} · ${esc(a.kind || "")}`
        ).join("<br>");
        box.innerHTML = block("Apelaciones", appeals) + block("Tickets abiertos", tickets)
            + block("Multicuentas", alts) + block("Radar", hij);
    } catch (e) {
        box.innerHTML = `<span class="sub">No se pudo cargar la cola.</span>`;
    }
}

async function previewSanction() {
    const box = $("preview-box");
    if (!box || !currentGuildId) return;
    const action = ($("preview-action") && $("preview-action").value) || "warn";
    const reason = ($("preview-reason") && $("preview-reason").value) || "Motivo";
    try {
        const p = await (await fetch(`/api/guilds/${currentGuildId}/preview/sanction?action=${encodeURIComponent(action)}&reason=${encodeURIComponent(reason)}`)).json();
        box.innerHTML = `<b>${esc(p.title)}</b><p>${esc(p.body)}</p>
            <p class="sub">Servidor · miembros · antigüedad · ID <code>${esc(p.fields && p.fields.id)}</code>
            ${p.verified ? "<br>✓ Servidor verificado por Dabot" : ""}
            ${p.links_warning ? "<br>El motivo incluye enlaces." : ""}</p>`;
    } catch {
        box.innerHTML = "No se pudo generar la vista previa.";
    }
}

function _lines(id) {
    const el = $(id);
    if (!el) return [];
    return String(el.value || "").split(/\n+/).map(s => s.trim()).filter(Boolean);
}

function addLinkBlockRow(domain, action) {
    const wrap = $("links-block-rows");
    if (!wrap) return;
    const row = document.createElement("div");
    row.className = "row link-block-row";
    row.style.gap = "8px";
    row.innerHTML = `<input class="link-block-domain" placeholder="grabify.link" value="${esc(domain || "")}">
        <select class="link-block-action">
            <option value="delete">Borrar</option>
            <option value="warn">Warn</option>
            <option value="timeout">Timeout</option>
            <option value="ban">Ban</option>
        </select>
        <button type="button" class="btn btn-ghost btn-sm" onclick="this.parentElement.remove()">Quitar</button>`;
    wrap.appendChild(row);
    const sel = row.querySelector(".link-block-action");
    if (sel) sel.value = action || "delete";
}

function fillLinksConfig(links) {
    links = links || {};
    if ($("cfg-links-enabled")) $("cfg-links-enabled").checked = !!links.enabled;
    if ($("cfg-links-block-all")) $("cfg-links-block-all").checked = !!links.block_all;
    if ($("cfg-links-ignore-staff")) $("cfg-links-ignore-staff").checked = links.ignore_staff !== false;
    if ($("cfg-links-default")) $("cfg-links-default").value = links.default_action || "delete";
    if ($("cfg-links-timeout")) $("cfg-links-timeout").value = links.timeout_minutes || 10;
    if ($("cfg-links-allow")) $("cfg-links-allow").value = (links.whitelist || []).join("\n");
    const wrap = $("links-block-rows");
    if (wrap) {
        wrap.innerHTML = "";
        (links.blocked || []).forEach(b => {
            if (typeof b === "string") addLinkBlockRow(b, "delete");
            else addLinkBlockRow(b.domain, b.action || "delete");
        });
        if (!(links.blocked || []).length) addLinkBlockRow("", "delete");
    }
    const tr = links.tracking || {};
    if ($("cfg-links-track")) $("cfg-links-track").checked = !!tr.enabled;
    if ($("cfg-links-referral")) $("cfg-links-referral").checked = tr.allow_referral !== false;
    if ($("cfg-links-track-action")) $("cfg-links-track-action").value = tr.action || "delete";
    if ($("cfg-links-ref-domains")) $("cfg-links-ref-domains").value = (tr.referral_domains || []).join("\n");
    if ($("cfg-links-track-params")) $("cfg-links-track-params").value = (tr.params || []).join("\n");
    const prem = !!(guildsCache[currentGuildId] && guildsCache[currentGuildId].is_premium);
    if ($("links-premium-gate")) $("links-premium-gate").classList.toggle("hidden", prem);
    if ($("links-premium-box")) $("links-premium-box").classList.toggle("hidden", !prem);
}

function collectLinksConfig() {
    const blocked = [];
    document.querySelectorAll(".link-block-row").forEach(row => {
        const domain = (row.querySelector(".link-block-domain") || {}).value || "";
        const action = (row.querySelector(".link-block-action") || {}).value || "delete";
        if (domain.trim()) blocked.push({ domain: domain.trim(), action });
    });
    return {
        enabled: $("cfg-links-enabled") ? $("cfg-links-enabled").checked : false,
        block_all: $("cfg-links-block-all") ? $("cfg-links-block-all").checked : false,
        ignore_staff: $("cfg-links-ignore-staff") ? $("cfg-links-ignore-staff").checked : true,
        default_action: ($("cfg-links-default") && $("cfg-links-default").value) || "delete",
        timeout_minutes: parseInt($("cfg-links-timeout") && $("cfg-links-timeout").value) || 10,
        whitelist: _lines("cfg-links-allow"),
        blocked,
        tracking: {
            enabled: $("cfg-links-track") ? $("cfg-links-track").checked : false,
            allow_referral: $("cfg-links-referral") ? $("cfg-links-referral").checked : true,
            action: ($("cfg-links-track-action") && $("cfg-links-track-action").value) || "delete",
            referral_domains: _lines("cfg-links-ref-domains"),
            params: _lines("cfg-links-track-params")
        }
    };
}

async function loadConfigRevisions() {
    const box = $("config-revisions");
    if (!box || !currentGuildId) return;
    try {
        const rows = await (await fetch(`/api/guilds/${currentGuildId}/config/revisions`)).json();
        if (!rows.length) { box.innerText = "Sin cambios registrados todavía."; return; }
        await resolveUsers(rows.map(r => r.user_id));
        box.innerHTML = rows.map(r =>
            `<div>${esc(r.created_at || "").slice(0, 19)} · ${userCell(r.user_id)} · <span class="mono">${esc(r.summary || "")}</span></div>`
        ).join("");
    } catch {
        box.innerText = "Sin historial.";
    }
}

async function loadAdminPrivacyRequests() {
    const tbody = document.getElementById("adm-privacy-body");
    if (!tbody) return;
    const filter = (document.getElementById("adm-privacy-filter") && document.getElementById("adm-privacy-filter").value) || "";
    tbody.innerHTML = `<tr><td colspan="7" class="empty">Cargando solicitudes RGPD…</td></tr>`;
    try {
        const url = filter ? `/api/admin/privacy_requests?status=${encodeURIComponent(filter)}` : `/api/admin/privacy_requests`;
        const res = await fetch(url);
        if (!res.ok) throw new Error("Error al cargar solicitudes");
        const data = await res.json();
        const reqs = data.requests || [];
        if (!reqs.length) {
            tbody.innerHTML = `<tr><td colspan="7" class="empty">No hay solicitudes que coincidan con este filtro.</td></tr>`;
            return;
        }
        tbody.innerHTML = reqs.map(r => {
            const isPending = r.status === "pending";
            const isDeletion = r.request_type === "deletion";
            const typeLabel = isDeletion ? `<span class="pill risk-high"><i class="fas fa-user-slash"></i> Supresión (Art. 17)</span>` : `<span class="pill risk-low"><i class="fas fa-file-export"></i> Exportación (Art. 15)</span>`;
            
            let statusLabel = `<span class="pill">${r.status}</span>`;
            if (r.status === "pending") statusLabel = `<span class="pill st-pending">⏳ Pendiente</span>`;
            else if (r.status === "approved" || r.status === "completed") statusLabel = `<span class="pill st-ok">✅ Procesado</span>`;
            else if (r.status === "rejected") statusLabel = `<span class="pill st-fail">❌ Rechazado</span>`;
            
            const backupBadge = r.encrypted_ip_backup ? `<span class="mono" style="font-size:0.75rem;color:var(--cyan)">🔒 ${esc(r.encrypted_ip_backup)}</span>` : `<span style="opacity:0.5">—</span>`;
            
            let actions = ``;
            if (isPending && isDeletion) {
                actions = `
                    <button class="btn btn-danger btn-xs" onclick="approvePrivacyDeletion(${r.id}, '${r.user_id}', '${esc(r.user_name || "")}')" title="Borrar datos personales y respaldar IP encriptada"><i class="fas fa-check"></i> Borrar y Encriptar IP</button>
                    <button class="btn btn-secondary btn-xs" onclick="rejectPrivacyRequest(${r.id})" title="Rechazar solicitud"><i class="fas fa-times"></i></button>
                `;
            } else {
                actions = `<span class="sub" style="font-size:0.75rem">${esc(r.admin_notes || "Completado")}</span>`;
            }

            return `
                <tr>
                    <td class="mono">#${r.id}</td>
                    <td><b>${esc(r.user_name || "Usuario")}</b><div class="mono" style="font-size:0.75rem">${r.user_id}</div></td>
                    <td>${typeLabel}</td>
                    <td class="mono" style="font-size:0.8rem">${esc(r.requested_at || "").slice(0, 16).replace("T", " ")}</td>
                    <td>${statusLabel}</td>
                    <td>${backupBadge}</td>
                    <td>${actions}</td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty error">Error: ${esc(e.message)}</td></tr>`;
    }
}

async function approvePrivacyDeletion(id, userId, userName) {
    if (!confirm(`¿Estás seguro de que deseas APROBAR y EJECUTAR la eliminación de datos del usuario ${userName || userId}?\n\nDe acuerdo con la directiva, se respaldará su IP encriptada con HMAC-SHA256 para prevenir multicuentas/abusos y se borrarán todos sus datos personales (perfil, cumpleaños, logros, etc.).`)) {
        return;
    }
    try {
        const res = await fetch(`/api/admin/privacy_requests/${id}/approve`, {
            method: "POST",
            headers: {"Content-Type": "application/json"}
        });
        const d = await res.json();
        if (!res.ok || !d.ok) throw new Error(d.detail || d.message || "Error al procesar");
        alert("✅ " + (d.message || "Eliminación ejecutada con éxito."));
        loadAdminPrivacyRequests();
    } catch (e) {
        alert("❌ Error: " + e.message);
    }
}

async function rejectPrivacyRequest(id) {
    const reason = prompt("Motivo del rechazo de la solicitud:", "No procede de conformidad con las políticas de seguridad");
    if (reason === null) return;
    try {
        const res = await fetch(`/api/admin/privacy_requests/${id}/reject`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ reason })
        });
        const d = await res.json();
        if (!res.ok || !d.ok) throw new Error(d.detail || "Error al rechazar");
        loadAdminPrivacyRequests();
    } catch (e) {
        alert("❌ Error: " + e.message);
    }
}

async function executeManualPrivacyDeletion() {
    const uidInput = document.getElementById("adm-manual-privacy-uid");
    const notesInput = document.getElementById("adm-manual-privacy-notes");
    if (!uidInput) return;
    const uid = uidInput.value.trim();
    if (!uid) {
        alert("Por favor introduce el ID de usuario de Discord.");
        return;
    }
    const notes = (notesInput && notesInput.value.trim()) || "Eliminación forzosa manual desde panel superusuario";
    
    if (!confirm(`¿Confirmas la ELIMINACIÓN DIRECTA de datos personales para el usuario ID ${uid}?\n\nSe purgarán sus datos personales y se almacenará el hash encriptado de su IP para protección del sistema.`)) {
        return;
    }
    
    try {
        const res = await fetch("/api/admin/privacy/manual_deletion", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ user_id: uid, notes: notes })
        });
        const d = await res.json();
        if (!res.ok || !d.ok) throw new Error(d.detail || d.message || "Error al ejecutar");
        alert("✅ " + (d.message || "Eliminación forzosa ejecutada correctamente."));
        uidInput.value = "";
        if (notesInput) notesInput.value = "";
        loadAdminPrivacyRequests();
    } catch (e) {
        alert("❌ Error: " + e.message);
    }
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function renderAntiNukeLogs(logs) {
    const box = $("antinuke-logs-container");
    if (!box) return;
    if (!logs || !logs.length) {
        box.innerHTML = '<div class="empty" style="padding:12px;background:rgba(0,0,0,0.2);border-radius:10px;">No hay activaciones registradas de Anti-Nuke en este servidor. ¡Todo en orden!</div>';
        return;
    }
    box.innerHTML = `
        <table class="glass" style="margin-top:8px;">
            <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción detectada</th><th>Veces</th><th>Castigo aplicado</th></tr></thead>
            <tbody>
                ${logs.map(l => `
                    <tr>
                        <td style="font-size:12px;color:var(--muted);">${new Date(l.created_at).toLocaleString()}</td>
                        <td><b>${escapeHtml(l.user_name || String(l.user_id))}</b></td>
                        <td><span class="badge" style="background:rgba(244,63,94,0.18);color:#f43f5e;">${escapeHtml(l.action_type)}</span></td>
                        <td>${l.count}</td>
                        <td><span class="badge" style="background:rgba(34,197,94,0.18);color:#22c55e;">${escapeHtml(l.action_taken)}</span></td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

async function loadAutoResponses() {
    const box = $("autoresponses-table-container");
    if (!box || !currentGuildId) return;
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/autoresponses`);
        if (!res.ok) return;
        const items = await res.json();
        if (!items || !items.length) {
            box.innerHTML = '<div class="empty" style="padding:12px;">No hay auto-respuestas configuradas en este servidor.</div>';
            return;
        }
        box.innerHTML = `
            <table class="glass" style="margin-top:8px;">
                <thead><tr><th>Palabra clave</th><th>Respuesta del bot</th><th style="width:70px;text-align:center;">Acción</th></tr></thead>
                <tbody>
                    ${items.map(it => `
                        <tr>
                            <td><code style="background:rgba(255,255,255,0.08);padding:3px 8px;border-radius:6px;color:#22d3ee;">${escapeHtml(it.trigger)}</code></td>
                            <td style="max-width:350px;word-break:break-word;">${escapeHtml(it.response)}</td>
                            <td style="text-align:center;">
                                <button class="btn btn-danger btn-sm" onclick="deleteAutoResponseWeb(${it.id})" title="Eliminar auto-respuesta" style="padding:4px 8px;">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (e) {
        console.error(e);
        box.innerHTML = '<div class="empty" style="color:#ef4444;">Error al cargar auto-respuestas.</div>';
    }
}

async function addAutoResponseWeb(e) {
    e.preventDefault();
    if (!currentGuildId) return;
    const trigger = $("ar-trigger")?.value.trim();
    const response = $("ar-response")?.value.trim();
    if (!trigger || !response) return;

    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/autoresponses`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ trigger, response })
        });
        if (res.ok) {
            toast("Auto-respuesta añadida correctamente.");
            if ($("ar-trigger")) $("ar-trigger").value = "";
            if ($("ar-response")) $("ar-response").value = "";
            loadAutoResponses();
        } else {
            const err = await res.json();
            toast(err.detail || "Error al añadir", "error");
        }
    } catch (e) {
        toast("Error de conexión", "error");
    }
}

async function deleteAutoResponseWeb(id) {
    if (!confirm("¿Deseas eliminar esta auto-respuesta?")) return;
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/autoresponses/${id}`, { method: "DELETE" });
        if (res.ok) {
            toast("Auto-respuesta eliminada.");
            loadAutoResponses();
        }
    } catch (e) {
        toast("Error al eliminar", "error");
    }
}

async function loadCustomCommands() {
    const box = $("customcommands-table-container");
    if (!box || !currentGuildId) return;
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/customcommands`);
        if (!res.ok) return;
        const items = await res.json();
        if (!items || !items.length) {
            box.innerHTML = '<div class="empty" style="padding:12px;">No hay comandos personalizados registrados aún.</div>';
            return;
        }
        box.innerHTML = `
            <table class="glass" style="margin-top:8px;">
                <thead><tr><th>Comando</th><th>Respuesta</th><th>Usos</th><th style="width:70px;text-align:center;">Acción</th></tr></thead>
                <tbody>
                    ${items.map(it => `
                        <tr>
                            <td><code style="background:rgba(255,255,255,0.08);padding:3px 8px;border-radius:6px;color:#38bdf8;">!${escapeHtml(it.trigger)}</code></td>
                            <td style="max-width:350px;word-break:break-word;">${escapeHtml(it.response)}</td>
                            <td><span class="badge" style="background:rgba(255,255,255,0.06);">${it.usage_count || 0}</span></td>
                            <td style="text-align:center;">
                                <button class="btn btn-danger btn-sm" onclick="deleteCustomCommandWeb('${escapeHtml(it.trigger)}')" title="Eliminar comando" style="padding:4px 8px;">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (e) {
        console.error(e);
        box.innerHTML = '<div class="empty" style="color:#ef4444;">Error al cargar comandos.</div>';
    }
}

async function addCustomCommandWeb(e) {
    e.preventDefault();
    if (!currentGuildId) return;
    const trigger = $("cc-trigger")?.value.trim();
    const response = $("cc-response")?.value.trim();
    if (!trigger || !response) return;

    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/customcommands`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ trigger, response })
        });
        if (res.ok) {
            toast("Comando personalizado creado.");
            if ($("cc-trigger")) $("cc-trigger").value = "";
            if ($("cc-response")) $("cc-response").value = "";
            loadCustomCommands();
        } else {
            const err = await res.json();
            toast(err.detail || "Error al crear", "error");
        }
    } catch (e) {
        toast("Error de conexión", "error");
    }
}

async function deleteCustomCommandWeb(trigger) {
    if (!confirm(`¿Deseas eliminar el comando !${trigger}?`)) return;
    try {
        const res = await fetch(`/api/guilds/${currentGuildId}/customcommands/${encodeURIComponent(trigger)}`, { method: "DELETE" });
        if (res.ok) {
            toast("Comando eliminado.");
            loadCustomCommands();
        }
    } catch (e) {
        toast("Error al eliminar", "error");
    }
}

