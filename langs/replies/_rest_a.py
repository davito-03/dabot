from _rest import add, fill_remaining

add("{prior} sanción(es) en este servidor", "{prior} sanción(es) en este servidor", "{prior} sanction(s) in this server", "{prior} sanction(s) sur ce serveur", "{prior} Sanktion(en) auf diesem Server", "{prior} sanção(ões) neste servidor", "{prior} sanzione/i in questo server", "このサーバーの制裁 {prior} 件", "이 서버 제재 {prior}건", "此服务器 {prior} 项处罚")
add("{severity} Toxicity Detected", "Toxicidad {severity} detectada", "{severity} Toxicity Detected", "Toxicité {severity} détectée", "{severity} Toxizität erkannt", "Toxicidade {severity} detetada", "Tossicità {severity} rilevata", "{severity} の有害発言を検出", "{severity} 유해성 감지", "检测到 {severity} 毒性")
add("{v0} Niveles\n{v1} Economía\n{v2} AutoMod\n{v3} Radar secuestro\n{v4} Bienvenida\n{v5} Logs\n{v6} Tickets → web",
    "{v0} Niveles\n{v1} Economía\n{v2} AutoMod\n{v3} Radar secuestro\n{v4} Bienvenida\n{v5} Logs\n{v6} Tickets → web",
    "{v0} Levels\n{v1} Economy\n{v2} AutoMod\n{v3} Hijack radar\n{v4} Welcome\n{v5} Logs\n{v6} Tickets → web",
    "{v0} Niveaux\n{v1} Économie\n{v2} AutoMod\n{v3} Radar piratage\n{v4} Bienvenue\n{v5} Journaux\n{v6} Tickets → web",
    "{v0} Level\n{v1} Wirtschaft\n{v2} AutoMod\n{v3} Hijack-Radar\n{v4} Willkommen\n{v5} Logs\n{v6} Tickets → Web",
    "{v0} Níveis\n{v1} Economia\n{v2} AutoMod\n{v3} Radar de sequestro\n{v4} Boas-vindas\n{v5} Logs\n{v6} Tickets → web",
    "{v0} Livelli\n{v1} Economia\n{v2} AutoMod\n{v3} Radar hijack\n{v4} Benvenuto\n{v5} Log\n{v6} Ticket → web",
    "{v0} レベル\n{v1} 経済\n{v2} AutoMod\n{v3} 乗っ取りレーダー\n{v4} 歓迎\n{v5} ログ\n{v6} チケット → web",
    "{v0} 레벨\n{v1} 경제\n{v2} AutoMod\n{v3} 탈취 레이더\n{v4} 환영\n{v5} 로그\n{v6} 티켓 → 웹",
    "{v0} 等级\n{v1} 经济\n{v2} AutoMod\n{v3} 劫持雷达\n{v4} 欢迎\n{v5} 日志\n{v6} 工单 → 网页")
add("{v0} personas · {v1} eventos · dabot.davito.es", "{v0} personas · {v1} eventos · dabot.davito.es", "{v0} people · {v1} events · dabot.davito.es", "{v0} personnes · {v1} événements · dabot.davito.es", "{v0} Personen · {v1} Ereignisse · dabot.davito.es", "{v0} pessoas · {v1} eventos · dabot.davito.es", "{v0} persone · {v1} eventi · dabot.davito.es", "{v0} 人 · {v1} 件 · dabot.davito.es", "{v0}명 · {v1}건 · dabot.davito.es", "{v0} 人 · {v1} 次事件 · dabot.davito.es")
add("¡Dabot ya está en tu servidor! 🦞", "¡Dabot ya está en tu servidor! 🦞", "Dabot is already in your server! 🦞", "Dabot est déjà sur ton serveur ! 🦞", "Dabot ist schon auf deinem Server! 🦞", "O Dabot já está no teu servidor! 🦞", "Dabot è già nel tuo server! 🦞", "Dabot はすでにサーバーにいます！🦞", "Dabot이 이미 서버에 있습니다! 🦞", "Dabot 已在你的服务器里！🦞")
add("¡Enhorabuena {mention}!\nLa respuesta era: **{v1}**\n\n🎁 Has ganado **{reward}** monedas para tu cartera.",
    "¡Enhorabuena {mention}!\nLa respuesta era: **{v1}**\n\n🎁 Has ganado **{reward}** monedas para tu cartera.",
    "Congrats {mention}!\nThe answer was: **{v1}**\n\n🎁 You won **{reward}** coins for your wallet.",
    "Bravo {mention} !\nLa réponse était : **{v1}**\n\n🎁 Tu as gagné **{reward}** pièces pour ton portefeuille.",
    "Glückwunsch {mention}!\nDie Antwort war: **{v1}**\n\n🎁 Du hast **{reward}** Münzen für deine Brieftasche gewonnen.",
    "Parabéns {mention}!\nA resposta era: **{v1}**\n\n🎁 Ganhaste **{reward}** moedas para a tua carteira.",
    "Complimenti {mention}!\nLa risposta era: **{v1}**\n\n🎁 Hai vinto **{reward}** monete per il portafoglio.",
    "おめでとう {mention}！\n正解は **{v1}**\n\n🎁 財布に **{reward}** コインを獲得。",
    "축하해요 {mention}!\n정답은 **{v1}**\n\n🎁 지갑에 **{reward}** 코인을 받았습니다.",
    "恭喜 {mention}！\n答案是：**{v1}**\n\n🎁 你赢得了 **{reward}** 金币，已入钱包。")
add("Última acción", "Última acción", "Last action", "Dernière action", "Letzte Aktion", "Última ação", "Ultima azione", "最後の操作", "마지막 작업", "上次操作")
add("Última huella", "Última huella", "Last fingerprint", "Dernière empreinte", "Letzter Fingerabdruck", "Última impressão", "Ultima impronta", "最後の指紋", "마지막 지문", "上次指纹")
add("• Dashboard: modules, Discord, sanctions, backups, templates\n• Verification: `/verify` + multi-account tracking\n• **Tickets**: transcripts live on the website\n• Global admin (creator): every server and alt cases\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Panel: módulos, Discord, sanciones, backups, plantillas\n• Verificación: `/verify` + rastreo de multicuentas\n• **Tickets**: el historial está en la web\n• Admin global (creador): todos los servidores y casos de alts\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Dashboard: modules, Discord, sanctions, backups, templates\n• Verification: `/verify` + multi-account tracking\n• **Tickets**: transcripts live on the website\n• Global admin (creator): every server and alt cases\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Panel : modules, Discord, sanctions, sauvegardes, modèles\n• Vérification : `/verify` + suivi multi-comptes\n• **Tickets** : l'historique est sur le web\n• Admin global (créateur) : tous les serveurs et dossiers d'alts\n• Premium : [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Panel: Module, Discord, Sanktionen, Backups, Vorlagen\n• Verifizierung: `/verify` + Mehrfachkonten\n• **Tickets**: Verlauf liegt im Web\n• Globaler Admin (Ersteller): alle Server und Alt-Fälle\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Painel: módulos, Discord, sanções, backups, modelos\n• Verificação: `/verify` + rastreio de multicontas\n• **Tickets**: o histórico fica na web\n• Admin global (criador): todos os servidores e casos de alts\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Pannello: moduli, Discord, sanzioni, backup, modelli\n• Verifica: `/verify` + tracciamento multi-account\n• **Ticket**: lo storico è sul web\n• Admin globale (creatore): tutti i server e i casi alt\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• パネル: モジュール、Discord、制裁、バックアップ、テンプレート\n• 認証: `/verify` + マルチアカウント追跡\n• **チケット**: 履歴はウェブ\n• グローバル管理（作成者）: 全サーバーとalt案件\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• 패널: 모듈, Discord, 제재, 백업, 템플릿\n• 인증: `/verify` + 다중 계정 추적\n• **티켓**: 기록은 웹에 있습니다\n• 전역 관리(제작자): 모든 서버와 alt 사건\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• 面板：模块、Discord、处罚、备份、模板\n• 验证：`/verify` + 多账号追踪\n• **工单**：记录在网站上\n• 全局管理（创建者）：全部服务器和小号案件\n• Premium：[dabot.davito.es/premium](https://dabot.davito.es/premium)")
add("• Panel: módulos, Discord, sanciones, backups, plantillas\n• Verificación: `/verify` + rastreo de multicuentas\n• **Tickets**: el historial se guarda en la web, no hace falta canal de transcripciones\n• Admin global (creador): todos los servidores y casos de alts\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Panel: módulos, Discord, sanciones, backups, plantillas\n• Verificación: `/verify` + rastreo de multicuentas\n• **Tickets**: el historial se guarda en la web, no hace falta canal de transcripciones\n• Admin global (creador): todos los servidores y casos de alts\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Dashboard: modules, Discord, sanctions, backups, templates\n• Verification: `/verify` + multi-account tracking\n• **Tickets**: history lives on the website, no transcript channel needed\n• Global admin (creator): every server and alt cases\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Panel : modules, Discord, sanctions, sauvegardes, modèles\n• Vérification : `/verify` + suivi multi-comptes\n• **Tickets** : l'historique est sur le web, pas besoin de salon de transcriptions\n• Admin global (créateur) : tous les serveurs et dossiers d'alts\n• Premium : [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Panel: Module, Discord, Sanktionen, Backups, Vorlagen\n• Verifizierung: `/verify` + Mehrfachkonten\n• **Tickets**: Verlauf im Web, kein Transkriptkanal nötig\n• Globaler Admin (Ersteller): alle Server und Alt-Fälle\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Painel: módulos, Discord, sanções, backups, modelos\n• Verificação: `/verify` + rastreio de multicontas\n• **Tickets**: o histórico fica na web, sem canal de transcrições\n• Admin global (criador): todos os servidores e casos de alts\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• Pannello: moduli, Discord, sanzioni, backup, modelli\n• Verifica: `/verify` + tracciamento multi-account\n• **Ticket**: lo storico è sul web, niente canale trascrizioni\n• Admin globale (creatore): tutti i server e i casi alt\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• パネル: モジュール、Discord、制裁、バックアップ、テンプレート\n• 認証: `/verify` + マルチアカウント追跡\n• **チケット**: 履歴はウェブ。書き起こしチャンネルは不要\n• グローバル管理（作成者）: 全サーバーとalt案件\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• 패널: 모듈, Discord, 제재, 백업, 템플릿\n• 인증: `/verify` + 다중 계정 추적\n• **티켓**: 기록은 웹에 있으며 기록 채널이 필요 없습니다\n• 전역 관리(제작자): 모든 서버와 alt 사건\n• Premium: [dabot.davito.es/premium](https://dabot.davito.es/premium)",
    "• 面板：模块、Discord、处罚、备份、模板\n• 验证：`/verify` + 多账号追踪\n• **工单**：记录在网站上，不需要记录频道\n• 全局管理（创建者）：全部服务器和小号案件\n• Premium：[dabot.davito.es/premium](https://dabot.davito.es/premium)")
add("• Panel: {DASHBOARD_URL}\n• Prefijo: `{v1}`\n• Idioma: `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• Panel: {DASHBOARD_URL}\n• Prefijo: `{v1}`\n• Idioma: `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• Dashboard: {DASHBOARD_URL}\n• Prefix: `{v1}`\n• Language: `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• Panel : {DASHBOARD_URL}\n• Préfixe : `{v1}`\n• Langue : `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• Panel: {DASHBOARD_URL}\n• Präfix: `{v1}`\n• Sprache: `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• Painel: {DASHBOARD_URL}\n• Prefixo: `{v1}`\n• Idioma: `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• Pannello: {DASHBOARD_URL}\n• Prefisso: `{v1}`\n• Lingua: `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• パネル: {DASHBOARD_URL}\n• 接頭辞: `{v1}`\n• 言語: `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• 패널: {DASHBOARD_URL}\n• 접두사: `{v1}`\n• 언어: `{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`",
    "• 面板：{DASHBOARD_URL}\n• 前缀：`{v1}`\n• 语言：`{v2}`\n• `/welcome setup` · `/antiraid setup` · `/verification setup`")
add("• `/radar status` — cuentas hackeadas (MrBeast / Nitro). Clic derecho → **Hijack check**\n• `/recovered` — si te silenciaron por secuestro y ya cambiaste la contraseña\n• `/verification setup` — verificación por navegador\n• `/antiraid setup` · AutoMod en el panel",
    "• `/radar status` — cuentas hackeadas (MrBeast / Nitro). Clic derecho → **Hijack check**\n• `/recovered` — si te silenciaron por secuestro y ya cambiaste la contraseña\n• `/verification setup` — verificación por navegador\n• `/antiraid setup` · AutoMod en el panel",
    "• `/radar status` — hijacked accounts (MrBeast / Nitro). Right-click → **Hijack check**\n• `/recovered` — after a hijack timeout, once you changed your password\n• `/verification setup` — browser verification\n• `/antiraid setup` · AutoMod in the dashboard",
    "• `/radar status` — comptes piratés (MrBeast / Nitro). Clic droit → **Hijack check**\n• `/recovered` — après un timeout de piratage, une fois le mot de passe changé\n• `/verification setup` — vérification navigateur\n• `/antiraid setup` · AutoMod dans le panel",
    "• `/radar status` — gehackte Konten (MrBeast / Nitro). Rechtsklick → **Hijack check**\n• `/recovered` — nach Hijack-Timeout, wenn das Passwort geändert ist\n• `/verification setup` — Browser-Verifizierung\n• `/antiraid setup` · AutoMod im Panel",
    "• `/radar status` — contas comprometidas (MrBeast / Nitro). Clique direito → **Hijack check**\n• `/recovered` — após timeout de sequestro, quando já mudaste a palavra-passe\n• `/verification setup` — verificação no navegador\n• `/antiraid setup` · AutoMod no painel",
    "• `/radar status` — account compromessi (MrBeast / Nitro). Clic destro → **Hijack check**\n• `/recovered` — dopo un timeout hijack, quando hai cambiato la password\n• `/verification setup` — verifica nel browser\n• `/antiraid setup` · AutoMod nel pannello",
    "• `/radar status` — 乗っ取られたアカウント（MrBeast / Nitro）。右クリック → **Hijack check**\n• `/recovered` — 乗っ取りタイムアウト後、パスワード変更済みなら\n• `/verification setup` — ブラウザ認証\n• `/antiraid setup` · パネルの AutoMod",
    "• `/radar status` — 탈취된 계정(MrBeast / Nitro). 우클릭 → **Hijack check**\n• `/recovered` — 탈취 타임아웃 후 비밀번호를 바꿨다면\n• `/verification setup` — 브라우저 인증\n• `/antiraid setup` · 패널의 AutoMod",
    "• `/radar status` — 被盗账号（MrBeast / Nitro）。右键 → **Hijack check**\n• `/recovered` — 劫持禁言后，若已改密码\n• `/verification setup` — 浏览器验证\n• `/antiraid setup` · 面板中的 AutoMod")
add("• `/radar status` — hijacked accounts (MrBeast / Nitro). Right-click → **Hijack check**\n• `/recovered` — after a hijack timeout, once you changed your password\n• `/verification setup` — browser verification\n• `/antiraid setup` · AutoMod in the dashboard",
    "• `/radar status` — cuentas hackeadas (MrBeast / Nitro). Clic derecho → **Hijack check**\n• `/recovered` — si te silenciaron por secuestro y ya cambiaste la contraseña\n• `/verification setup` — verificación por navegador\n• `/antiraid setup` · AutoMod en el panel",
    "• `/radar status` — hijacked accounts (MrBeast / Nitro). Right-click → **Hijack check**\n• `/recovered` — after a hijack timeout, once you changed your password\n• `/verification setup` — browser verification\n• `/antiraid setup` · AutoMod in the dashboard",
    "• `/radar status` — comptes piratés (MrBeast / Nitro). Clic droit → **Hijack check**\n• `/recovered` — après un timeout de piratage, une fois le mot de passe changé\n• `/verification setup` — vérification navigateur\n• `/antiraid setup` · AutoMod dans le panel",
    "• `/radar status` — gehackte Konten (MrBeast / Nitro). Rechtsklick → **Hijack check**\n• `/recovered` — nach Hijack-Timeout, wenn das Passwort geändert ist\n• `/verification setup` — Browser-Verifizierung\n• `/antiraid setup` · AutoMod im Panel",
    "• `/radar status` — contas comprometidas (MrBeast / Nitro). Clique direito → **Hijack check**\n• `/recovered` — após timeout de sequestro, quando já mudaste a palavra-passe\n• `/verification setup` — verificação no navegador\n• `/antiraid setup` · AutoMod no painel",
    "• `/radar status` — account compromessi (MrBeast / Nitro). Clic destro → **Hijack check**\n• `/recovered` — dopo un timeout hijack, quando hai cambiato la password\n• `/verification setup` — verifica nel browser\n• `/antiraid setup` · AutoMod nel pannello",
    "• `/radar status` — 乗っ取られたアカウント（MrBeast / Nitro）。右クリック → **Hijack check**\n• `/recovered` — 乗っ取りタイムアウト後、パスワード変更済みなら\n• `/verification setup` — ブラウザ認証\n• `/antiraid setup` · パネルの AutoMod",
    "• `/radar status` — 탈취된 계정(MrBeast / Nitro). 우클릭 → **Hijack check**\n• `/recovered` — 탈취 타임아웃 후 비밀번호를 바꿨다면\n• `/verification setup` — 브라우저 인증\n• `/antiraid setup` · 패널의 AutoMod",
    "• `/radar status` — 被盗账号（MrBeast / Nitro）。右键 → **Hijack check**\n• `/recovered` — 劫持禁言后，若已改密码\n• `/verification setup` — 浏览器验证\n• `/antiraid setup` · 面板中的 AutoMod")
add("⏰ Demasiados intentos. El número era **{number}**.", "⏰ Demasiados intentos. El número era **{number}**.", "⏰ Too many tries. The number was **{number}**.", "⏰ Trop d'essais. Le nombre était **{number}**.", "⏰ Zu viele Versuche. Die Zahl war **{number}**.", "⏰ Demasiadas tentativas. O número era **{number}**.", "⏰ Troppi tentativi. Il numero era **{number}**.", "⏰ 試行が多すぎます。数字は **{number}** でした。", "⏰ 시도가 너무 많습니다. 숫자는 **{number}**이었습니다.", "⏰ 尝试过多。数字是 **{number}**。")
add("⏰ Message Scheduled", "⏰ Mensaje programado", "⏰ Message Scheduled", "⏰ Message programmé", "⏰ Nachricht geplant", "⏰ Mensagem programada", "⏰ Messaggio programmato", "⏰ メッセージを予約しました", "⏰ 메시지가 예약됨", "⏰ 已安排消息")
add("⏰ Reminder set for **{time}** from now!", "⏰ Recordatorio en **{time}**.", "⏰ Reminder set for **{time}** from now!", "⏰ Rappel dans **{time}** !", "⏰ Erinnerung in **{time}**!", "⏰ Lembrete daqui a **{time}**!", "⏰ Promemoria tra **{time}**!", "⏰ **{time}** 後にリマインダー", "⏰ **{time}** 뒤에 알림이 설정됨!", "⏰ 已设置 **{time}** 后的提醒！")
add("⏰ Restore Cancelled", "⏰ Restauración cancelada", "⏰ Restore Cancelled", "⏰ Restauration annulée", "⏰ Wiederherstellung abgebrochen", "⏰ Restauro cancelado", "⏰ Ripristino annullato", "⏰ 復元をキャンセル", "⏰ 복원 취소됨", "⏰ 已取消恢复")
add("⏰ Time's up! Answer was {result}.", "⏰ ¡Se acabó el tiempo! La respuesta era {result}.", "⏰ Time's up! Answer was {result}.", "⏰ Temps écoulé ! La réponse était {result}.", "⏰ Zeit um! Die Antwort war {result}.", "⏰ Acabou o tempo! A resposta era {result}.", "⏰ Tempo scaduto! La risposta era {result}.", "⏰ 時間切れ！答えは {result}。", "⏰ 시간 종료! 정답은 {result}.", "⏰ 时间到！答案是 {result}。")
add("⏰ Time's up! The number was **{number}**.", "⏰ ¡Se acabó el tiempo! El número era **{number}**.", "⏰ Time's up! The number was **{number}**.", "⏰ Temps écoulé ! Le nombre était **{number}**.", "⏰ Zeit um! Die Zahl war **{number}**.", "⏰ Acabou o tempo! O número era **{number}**.", "⏰ Tempo scaduto! Il numero era **{number}**.", "⏰ 時間切れ！数字は **{number}** でした。", "⏰ 시간 종료! 숫자는 **{number}**이었습니다.", "⏰ 时间到！数字是 **{number}**。")
add("⏰ You can give reputation to {mention} again in **{hours_left}h {minutes_left}m**.", "⏰ Puedes volver a dar reputación a {mention} en **{hours_left}h {minutes_left}m**.", "⏰ You can give reputation to {mention} again in **{hours_left}h {minutes_left}m**.", "⏰ Tu pourras redonner de la réputation à {mention} dans **{hours_left}h {minutes_left}m**.", "⏰ Du kannst {mention} in **{hours_left}h {minutes_left}m** wieder Reputation geben.", "⏰ Podes voltar a dar reputação a {mention} em **{hours_left}h {minutes_left}m**.", "⏰ Potrai ridare reputazione a {mention} tra **{hours_left}h {minutes_left}m**.", "⏰ {mention} にまた評判を贈れるのは **{hours_left}時間 {minutes_left}分** 後です。", "⏰ {mention}에게 다시 평판을 줄 수 있는 시간은 **{hours_left}시간 {minutes_left}분** 후입니다.", "⏰ 你可以在 **{hours_left} 小时 {minutes_left} 分钟**后再给 {mention} 声望。")
add("⏳ Tu rol temporal **{name}** en el servidor **{name}** ha expirado.", "⏳ Tu rol temporal **{name}** en el servidor **{name}** ha expirado.", "⏳ Your temporary role **{name}** in **{name}** has expired.", "⏳ Ton rôle temporaire **{name}** sur **{name}** a expiré.", "⏳ Deine temporäre Rolle **{name}** auf **{name}** ist abgelaufen.", "⏳ O teu cargo temporário **{name}** em **{name}** expirou.", "⏳ Il tuo ruolo temporaneo **{name}** in **{name}** è scaduto.", "⏳ **{name}** サーバーの一時ロール **{name}** が期限切れです。", "⏳ **{name}** 서버의 임시 역할 **{name}**이(가) 만료되었습니다.", "⏳ 你在 **{name}** 的临时身份组 **{name}** 已过期。")
add("⏳ Wait for your turn!", "⏳ ¡Espera tu turno!", "⏳ Wait for your turn!", "⏳ Attends ton tour !", "⏳ Warte auf deinen Zug!", "⏳ Espera a tua vez!", "⏳ Aspetta il tuo turno!", "⏳ 自分の番を待って！", "⏳ 당신 차례를 기다리세요!", "⏳ 等你的回合！")
add("⏳ ¡Cálmate mi cielo! Este comando tiene un cooldown. Debes esperar **{time_text}** antes de volver a usarlo. 🌸",
    "⏳ ¡Cálmate mi cielo! Este comando tiene un cooldown. Debes esperar **{time_text}** antes de volver a usarlo. 🌸",
    "⏳ Easy. This command is on cooldown. Wait **{time_text}** before using it again. 🌸",
    "⏳ Du calme. Cette commande a un cooldown. Attends **{time_text}** avant de la réutiliser. 🌸",
    "⏳ Ruhig. Dieser Befehl hat Cooldown. Warte **{time_text}**, bevor du ihn wieder nutzt. 🌸",
    "⏳ Calma. Este comando tem cooldown. Espera **{time_text}** antes de o voltares a usar. 🌸",
    "⏳ Calma. Questo comando ha un cooldown. Aspetta **{time_text}** prima di riusarlo. 🌸",
    "⏳ ちょっと待って。このコマンドはクールダウン中。**{time_text}** 後に再使用できます。🌸",
    "⏳ 진정해요. 이 명령은 쿨다운 중입니다. **{time_text}** 후에 다시 쓰세요. 🌸",
    "⏳ 先缓一缓。此命令在冷却中。请等 **{time_text}** 再使用。🌸")
add("☢️ Raid drill (superusuario)", "☢️ Simulacro de raid (superusuario)", "☢️ Raid drill (superuser)", "☢️ Exercice de raid (superutilisateur)", "☢️ Raid-Drill (Superuser)", "☢️ Simulacro de raid (superutilizador)", "☢️ Esercitazione raid (superutente)", "☢️ レイド訓練（スーパーユーザー）", "☢️ 레이드 훈련(슈퍼유저)", "☢️ 突袭演练（超级用户）")
add("☢️ SUPER OWNER ONLY: Simulate a raid event.", "☢️ SOLO SUPER OWNER: Simula un evento de raid.", "☢️ SUPER OWNER ONLY: Simulate a raid event.", "☢️ SUPER OWNER UNIQUEMENT : simule un raid.", "☢️ NUR SUPER-OWNER: Raid-Ereignis simulieren.", "☢️ SÓ SUPER OWNER: Simula um evento de raid.", "☢️ SOLO SUPER OWNER: simula un evento raid.", "☢️ スーパーオーナー専用: レイドを模擬します。", "☢️ 슈퍼 오너 전용: 레이드 이벤트를 시뮬레이션합니다.", "☢️ 仅超级所有者：模拟突袭事件。")
add("⚔️ Aventura IA — Capítulo {v0}", "⚔️ Aventura IA — Capítulo {v0}", "⚔️ AI Adventure — Chapter {v0}", "⚔️ Aventure IA — Chapitre {v0}", "⚔️ KI-Abenteuer — Kapitel {v0}", "⚔️ Aventura IA — Capítulo {v0}", "⚔️ Avventura IA — Capitolo {v0}", "⚔️ AI冒険 — 第 {v0} 章", "⚔️ AI 모험 — {v0}장", "⚔️ AI 冒险 — 第 {v0} 章")
add("⚔️ Battle Challenge!", "⚔️ ¡Desafío de combate!", "⚔️ Battle Challenge!", "⚔️ Défi de combat !", "⚔️ Kampfherausforderung!", "⚔️ Desafio de combate!", "⚔️ Sfida di battaglia!", "⚔️ バトル挑戦！", "⚔️ 전투 도전!", "⚔️ 战斗挑战！")
add("⚔️ Inicia una aventura RPG interactiva donde la IA narra y genera ilustraciones dinámicas.",
    "⚔️ Inicia una aventura RPG interactiva donde la IA narra y genera ilustraciones dinámicas.",
    "⚔️ Start an interactive RPG adventure where the AI narrates and draws live art.",
    "⚔️ Lance une aventure RPG interactive où l'IA raconte et dessine en direct.",
    "⚔️ Startet ein interaktives RPG, in dem die KI erzählt und live zeichnet.",
    "⚔️ Inicia uma aventura RPG interativa em que a IA narra e gera ilustrações.",
    "⚔️ Avvia un'avventura RPG interattiva in cui l'IA narra e disegna dal vivo.",
    "⚔️ IAが語り、挿絵を描くインタラクティブRPGを開始します。",
    "⚔️ AI가 서술하고 그림을 그리는 인터랙티브 RPG를 시작합니다.",
    "⚔️ 开始一场互动 RPG：AI 旁白并生成动态插图。")
add("⚙️ Server configuration commands.", "⚙️ Comandos de configuración del servidor.", "⚙️ Server configuration commands.", "⚙️ Commandes de configuration du serveur.", "⚙️ Server-Konfigurationsbefehle.", "⚙️ Comandos de configuração do servidor.", "⚙️ Comandi di configurazione del server.", "⚙️ サーバー設定コマンド。", "⚙️ 서버 설정 명령.", "⚙️ 服务器配置命令。")

