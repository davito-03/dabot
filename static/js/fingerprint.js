window.dabotDeviceId = function dabotDeviceId() {
    try {
        let id = localStorage.getItem("dabot_did");
        if (!id) {
            const bytes = crypto.getRandomValues(new Uint8Array(16));
            id = Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
            localStorage.setItem("dabot_did", id);
        }
        return id;
    } catch (e) {
        return "";
    }
};

window.dabotWebrtcIps = async function dabotWebrtcIps() {
    const found = [];
    const push = (ip) => {
        if (!ip || ip.endsWith(".local") || ip.indexOf(":") === 0) return;
        if (found.indexOf(ip) >= 0) return;
        found.push(ip);
    };
    try {
        const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.cloudflare.com:3478" }] });
        pc.createDataChannel("d");
        await new Promise((resolve) => {
            const done = () => { try { pc.close(); } catch (e) {} resolve(); };
            const t = setTimeout(done, 1100);
            pc.onicecandidate = (ev) => {
                const cand = (ev && ev.candidate && ev.candidate.candidate) || "";
                if (!cand) {
                    clearTimeout(t);
                    done();
                    return;
                }
                const parts = cand.split(" ");
                if (parts.length >= 5) push(parts[4]);
            };
            pc.createOffer().then((o) => pc.setLocalDescription(o)).catch(done);
        });
    } catch (e) { /* WebRTC blocked is common; not enough to fail */ }
    return found.slice(0, 8);
};

window.dabotFingerprint = async function dabotFingerprint() {
    const canvas = (() => {
        try {
            const c = document.createElement("canvas");
            const x = c.getContext("2d");
            x.textBaseline = "top";
            x.font = "16px Inter, Arial";
            x.fillStyle = "#00ff88";
            x.fillText("dabot-langosta", 4, 4);
            return String(c.toDataURL()).slice(-80);
        } catch (e) {
            return "";
        }
    })();
    let webgl = "";
    try {
        const c = document.createElement("canvas");
        const gl = c.getContext("webgl") || c.getContext("experimental-webgl");
        if (gl) {
            const dbg = gl.getExtension("WEBGL_debug_renderer_info");
            if (dbg) {
                webgl = gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) + "|" + gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL);
            }
        }
    } catch (e) { webgl = ""; }
    const webrtc_ips = await window.dabotWebrtcIps();
    return {
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
        lang: navigator.language || "",
        platform: navigator.platform || "",
        hardware: navigator.hardwareConcurrency || 0,
        memory: navigator.deviceMemory || 0,
        screen: `${screen.width}x${screen.height}@${window.devicePixelRatio || 1}`,
        touch: navigator.maxTouchPoints || 0,
        canvas,
        webgl,
        webrtc_ips
    };
};
