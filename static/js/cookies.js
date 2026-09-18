/**
 * Cookie notice for Dabot (AEPD / LSSI art. 22.2 / GDPR).
 * Only strictly necessary cookies are used, so the first layer is an
 * information panel (Entendido), not an accept/reject of advertising.
 */
(() => {
    const NOTICE_KEY = "dabot_cookie_notice";
    const NOTICE_VER = "2026-08";
    const MAX_AGE = 400 * 24 * 3600; // ~13 months (AEPD)

    const T = {
        es: {
            title: "Uso de cookies y datos técnicos",
            body: "Dabot utiliza cookies técnicas estrictamente necesarias para el funcionamiento del servicio: mantenimiento de sesión, protección frente a envíos no autorizados (CSRF), preferencias de idioma y medidas técnicas de seguridad. No utilizamos cookies publicitarias ni de seguimiento analítico de terceros.",
            ok: "Entendido",
            settings: "Ver detalles",
            policy: "Política de cookies",
            reopen: "Cookies",
            modalTitle: "Cookies y almacenamiento técnico",
            modalLead: "Los identificadores técnicos utilizados son esenciales para la prestación segura de los servicios solicitados conforme al art. 22.2 de la LSSI y el RGPD.",
            close: "Cerrar",
            ipTitle: "Seguridad y datos de conectividad",
            ipBody: "Para garantizar la seguridad de la plataforma y prevenir accesos abusivos o automatizados, los datos técnicos de conexión se procesan de forma estrictamente seudonimizada mediante algoritmos criptográficos. La información técnica se conserva de forma confidencial y segura exclusivamente para la auditoría técnica.",
            tblName: "Nombre",
            tblFor: "Finalidad",
            tblDur: "Caducidad",
            tblKind: "Tipo",
            nec: "Necesaria",
        },
        en: {
            title: "Cookies and technical data",
            body: "Dabot only uses strictly necessary technical cookies: session management, CSRF security, language preferences, and security validation. We do not use advertising or third-party tracking cookies.",
            ok: "Got it",
            settings: "Cookie details",
            policy: "Cookie policy",
            reopen: "Cookies",
            modalTitle: "Technical cookies and storage",
            modalLead: "All technical cookies are strictly essential for providing the requested service securely, in accordance with applicable ePrivacy and GDPR regulations.",
            close: "Close",
            ipTitle: "Security and connectivity data",
            ipBody: "To ensure platform integrity and prevent automated abuse, technical connection parameters are processed using pseudonymous cryptographic algorithms. Technical records are securely retained solely for security audits.",
            tblName: "Name",
            tblFor: "Purpose",
            tblDur: "Expiry",
            tblKind: "Type",
            nec: "Necessary",
        },
        fr: {
            title: "Cookies et données réseau",
            body: "Davito n’utilise que des cookies techniques : session, CSRF, langue et, si tu te vérifies, un identifiant d’appareil anti multi-comptes. Pas de pub ni d’analytics tiers. Lors de la vérif, l’IP est hashée : le staff du serveur voit des codes, pas l’IP en clair.",
            ok: "Compris",
            settings: "Voir les cookies",
            policy: "Politique cookies",
            reopen: "Cookies",
            modalTitle: "Cookies utilisés par Dabot",
            modalLead: "Tous sont nécessaires au service demandé. Base : art. 22.2 LSSI et art. 6.1.b/f RGPD pour l’IP.",
            close: "Fermer",
            ipTitle: "IP et empreinte (pas des cookies)",
            ipBody: "À la vérification, l’IP est vue puis hashée pour le staff de ce serveur. Empreinte navigateur et WebRTC peuvent servir à détecter un VPN. Conservation typique : 180 jours.",
            tblName: "Nom", tblFor: "Usage", tblDur: "Durée", tblKind: "Type", nec: "Nécessaire",
        },
        de: {
            title: "Cookies und Netzdaten",
            body: "Davito nutzt nur technische Cookies: Sitzung, CSRF, Sprache und bei der Verifizierung eine Geräte-ID gegen Mehrfachkonten. Keine Werbung, keine Dritt-Analytics. Die IP wird gehasht gespeichert; das Server-Team sieht Codes, nicht die Klar-IP.",
            ok: "Verstanden",
            settings: "Cookies ansehen",
            policy: "Cookie-Richtlinie",
            reopen: "Cookies",
            modalTitle: "Cookies von Dabot",
            modalLead: "Alle sind für den angeforderten Dienst nötig. Grundlage: LSSI Art. 22.2 und DSGVO Art. 6.1.b/f für die IP.",
            close: "Schließen",
            ipTitle: "IP und Fingerprint (keine Cookies)",
            ipBody: "Bei der Verifizierung wird die IP gehasht. Browser-Fingerprint und WebRTC können VPNs erkennen. Typische Speicherung: 180 Tage.",
            tblName: "Name", tblFor: "Zweck", tblDur: "Laufzeit", tblKind: "Art", nec: "Erforderlich",
        },
        pt: {
            title: "Cookies e dados de rede",
            body: "A Davito só usa cookies técnicos: sessão, CSRF, idioma e, na verificação, um id de dispositivo contra multicontas. Sem publicidade nem analytics de terceiros. Na verificação a IP fica hashed: o staff vê códigos, não a IP em claro.",
            ok: "Compreendi",
            settings: "Ver cookies",
            policy: "Política de cookies",
            reopen: "Cookies",
            modalTitle: "Cookies do Dabot",
            modalLead: "Todas são necessárias ao serviço que pedes. Base: art. 22.2 LSSI e art. 6.1.b/f RGPD para a IP.",
            close: "Fechar",
            ipTitle: "IP e impressão (não são cookies)",
            ipBody: "Na verificação a IP é hashed para o staff desse servidor. A impressão do browser e WebRTC podem detetar VPN. Conservação típica: 180 dias.",
            tblName: "Nome", tblFor: "Para quê", tblDur: "Validade", tblKind: "Tipo", nec: "Necessária",
        },
        it: {
            title: "Cookie e dati di rete",
            body: "Davito usa solo cookie tecnici: sessione, CSRF, lingua e, in verifica, un id dispositivo anti multi-account. Niente ads né analytics di terzi. In verifica l’IP è hashata: lo staff vede codici, non l’IP in chiaro.",
            ok: "Ho capito",
            settings: "Vedi i cookie",
            policy: "Informativa cookie",
            reopen: "Cookie",
            modalTitle: "Cookie di Dabot",
            modalLead: "Tutti sono necessari al servizio che chiedi. Base: art. 22.2 LSSI e art. 6.1.b/f GDPR per l’IP.",
            close: "Chiudi",
            ipTitle: "IP e impronta (non sono cookie)",
            ipBody: "In verifica l’IP viene hashata per lo staff di quel server. Impronta del browser e WebRTC possono rilevare VPN. Conservazione tipica: 180 giorni.",
            tblName: "Nome", tblFor: "Scopo", tblDur: "Scadenza", tblKind: "Tipo", nec: "Necessario",
        },
    };

    const COOKIES = [
        { name: "session_id", purpose: { es: "Sesión tras iniciar con Discord", en: "Session after Discord login", fr: "Session après connexion Discord", de: "Sitzung nach Discord-Login", pt: "Sessão após login Discord", it: "Sessione dopo il login Discord" }, dur: "7 días / 7 days", http: "HttpOnly" },
        { name: "csrf_token", purpose: { es: "Evitar envíos falsos de formularios", en: "Stop forged form posts", fr: "Anti-falsification des formulaires", de: "Schutz vor gefälschten Formularen", pt: "Evitar envios falsos de formulários", it: "Protezione CSRF dei form" }, dur: "7 días / 7 days", http: "" },
        { name: "dabot_did", purpose: { es: "Identificar el dispositivo en la verificación anti-multicuenta", en: "Device id for anti-alt verification", fr: "Id appareil anti multi-comptes", de: "Geräte-ID gegen Mehrfachkonten", pt: "Id do dispositivo na verificação", it: "Id dispositivo anti multi-account" }, dur: "13 meses / 13 months", http: "HttpOnly" },
        { name: "dabot_lang_manual", purpose: { es: "Recordar el idioma que elegiste", en: "Remember the language you picked", fr: "Mémoriser la langue choisie", de: "Gewählte Sprache merken", pt: "Lembrar o idioma escolhido", it: "Ricorda la lingua scelta" }, dur: "13 meses / 13 months", http: "" },
        { name: "dabot_cookie_notice", purpose: { es: "Recordar que ya viste este aviso", en: "Remember you dismissed this notice", fr: "Mémoriser que tu as vu l’avis", de: "Merken, dass der Hinweis gelesen wurde", pt: "Lembrar que já viste este aviso", it: "Ricorda che hai visto l’avviso" }, dur: "13 meses / 13 months", http: "" },
        { name: "dabot_oauth_state / pkce", purpose: { es: "Login OAuth (se borran al entrar)", en: "OAuth login (deleted after sign-in)", fr: "Login OAuth (supprimés après)", de: "OAuth-Login (danach gelöscht)", pt: "Login OAuth (apagados depois)", it: "Login OAuth (poi cancellati)" }, dur: "minutos / minutes", http: "" },
    ];

    function lang() {
        const l = (document.documentElement.lang || "es").split("-")[0];
        return T[l] ? l : (T.es && l !== "en" ? "es" : "en");
    }
    function t(key) {
        const l = lang();
        return (T[l] && T[l][key]) || T.es[key] || key;
    }
    function purpose(row) {
        const l = lang();
        return row.purpose[l] || row.purpose.es;
    }
    function cookieAttrs() {
        let a = ";path=/;max-age=" + MAX_AGE + ";samesite=lax";
        if (location.protocol === "https:") a += ";secure";
        return a;
    }
    function readCookie(name) {
        const m = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "=([^;]*)"));
        return m ? decodeURIComponent(m[1]) : "";
    }
    function writeCookie(name, value) {
        document.cookie = name + "=" + encodeURIComponent(value) + cookieAttrs();
    }
    function alreadyAcked() {
        if (readCookie(NOTICE_KEY) === NOTICE_VER) return true;
        try {
            const raw = localStorage.getItem(NOTICE_KEY);
            if (!raw) return false;
            if (raw === NOTICE_VER) return true;
            const parsed = JSON.parse(raw);
            if (!parsed || parsed.v !== NOTICE_VER) return false;
            return (Date.now() - Number(parsed.t || 0)) < MAX_AGE * 1000;
        } catch (e) {
            return false;
        }
    }
    function persistAck() {
        writeCookie(NOTICE_KEY, NOTICE_VER);
        try {
            localStorage.setItem(NOTICE_KEY, JSON.stringify({ v: NOTICE_VER, t: Date.now() }));
        } catch (e) {}
        const langCk = readCookie("dabot_lang_manual");
        if (langCk) writeCookie("dabot_lang_manual", langCk);
    }

    function bannerHtml() {
        return `<div class="ck-banner glass" role="dialog" aria-labelledby="ck-title" aria-describedby="ck-body">
            <div class="ck-copy">
                <strong id="ck-title">${t("title")}</strong>
                <p id="ck-body">${t("body")}</p>
            </div>
            <div class="ck-actions">
                <button type="button" class="btn btn-ghost btn-sm" data-ck="open">${t("settings")}</button>
                <a class="btn btn-ghost btn-sm" href="/cookies">${t("policy")}</a>
                <button type="button" class="btn btn-primary btn-sm" data-ck="ok">${t("ok")}</button>
            </div>
        </div>`;
    }

    function modalHtml() {
        const rows = COOKIES.map((c) => `<tr>
            <td class="mono">${c.name}</td>
            <td>${purpose(c)}</td>
            <td>${c.dur}</td>
            <td><span class="pill">${t("nec")}</span></td>
        </tr>`).join("");
        return `<div class="ck-modal-back" role="presentation">
            <div class="ck-modal panel glass" role="dialog" aria-modal="true" aria-labelledby="ck-m-title">
                <h2 id="ck-m-title">${t("modalTitle")}</h2>
                <p class="sub">${t("modalLead")}</p>
                <div style="overflow:auto;margin:12px 0">
                    <table class="ck-table">
                        <thead><tr><th>${t("tblName")}</th><th>${t("tblFor")}</th><th>${t("tblDur")}</th><th>${t("tblKind")}</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
                <h3>${t("ipTitle")}</h3>
                <p class="sub">${t("ipBody")}</p>
                <p class="sub"><a href="/cookies">${t("policy")}</a> · <a href="/privacy">${document.documentElement.lang === "en" ? "Privacy" : "Privacidad"}</a></p>
                <div class="ck-actions" style="justify-content:flex-end;margin-top:12px">
                    <button type="button" class="btn btn-primary btn-sm" data-ck="close">${t("close")}</button>
                </div>
            </div>
        </div>`;
    }

    function mount() {
        if (document.getElementById("ck-root")) return;
        const root = document.createElement("div");
        root.id = "ck-root";
        document.body.appendChild(root);
        const chip = document.createElement("button");
        chip.type = "button";
        chip.id = "ck-reopen";
        chip.className = "ck-reopen";
        chip.textContent = t("reopen");
        chip.addEventListener("click", openModal);
        document.body.appendChild(chip);
        const seen = alreadyAcked();
        chip.style.display = seen ? "" : "none";
        if (seen) persistAck();
        else showBanner();
        bind();
    }

    function showBanner() {
        const root = document.getElementById("ck-root");
        if (!root) return;
        root.innerHTML = bannerHtml();
        bind();
    }
    function hideBanner() {
        const root = document.getElementById("ck-root");
        if (root) root.querySelector(".ck-banner")?.remove();
    }
    function openModal() {
        closeModal();
        const wrap = document.createElement("div");
        wrap.id = "ck-modal-wrap";
        wrap.innerHTML = modalHtml();
        document.body.appendChild(wrap);
        bind();
    }
    function closeModal() {
        document.getElementById("ck-modal-wrap")?.remove();
    }
    function ack() {
        persistAck();
        hideBanner();
        closeModal();
        const chip = document.getElementById("ck-reopen");
        if (chip) chip.style.display = "";
    }
    function bind() {
        document.querySelectorAll("[data-ck]").forEach((el) => {
            el.onclick = () => {
                const a = el.getAttribute("data-ck");
                if (a === "ok") ack();
                else if (a === "open") openModal();
                else if (a === "close") closeModal();
            };
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mount);
    } else {
        mount();
    }
    document.addEventListener("dabot:lang", () => {
        const reopen = document.getElementById("ck-reopen");
        if (reopen) reopen.textContent = t("reopen");
        if (alreadyAcked()) {
            hideBanner();
            persistAck();
            return;
        }
        if (document.querySelector(".ck-banner")) showBanner();
        if (document.getElementById("ck-modal-wrap")) openModal();
    });
})();
