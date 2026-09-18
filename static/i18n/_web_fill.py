#!/usr/bin/env python3
"""Merge missing web UI keys into static/i18n/*.json and rebuild i18n.js STR."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JS = ROOT.parent / "js" / "i18n.js"
LANGS = ("es", "en", "fr", "de", "pt", "it", "ja", "ko", "zh")

# key -> (es, en, fr, de, pt, it, ja, ko, zh)
NEW: dict[str, tuple[str, ...]] = {
    "nav.terms": (
        "Términos", "Terms", "Conditions", "Bedingungen", "Termos", "Termini", "利用規約", "약관", "条款",
    ),
    "title.home": (
        "Dabot — la comunidad, organizada",
        "Dabot — community, organized",
        "Dabot — la communauté, organisée",
        "Dabot — Community, organisiert",
        "Dabot — a comunidade, organizada",
        "Dabot — la community, organizzata",
        "Dabot — コミュニティを整理",
        "Dabot — 정리된 커뮤니티",
        "Dabot — 井然有序的社区",
    ),
    "title.privacy": (
        "Privacidad — Dabot", "Privacy — Dabot", "Confidentialité — Dabot", "Datenschutz — Dabot",
        "Privacidade — Dabot", "Privacy — Dabot", "プライバシー — Dabot", "개인정보 — Dabot", "隐私 — Dabot",
    ),
    "title.terms": (
        "Términos — Dabot", "Terms — Dabot", "Conditions — Dabot", "Nutzungsbedingungen — Dabot",
        "Termos — Dabot", "Termini — Dabot", "利用規約 — Dabot", "이용약관 — Dabot", "条款 — Dabot",
    ),
    "title.premium": (
        "Premium — Dabot", "Premium — Dabot", "Premium — Dabot", "Premium — Dabot",
        "Premium — Dabot", "Premium — Dabot", "Premium — Dabot", "Premium — Dabot", "Premium — Dabot",
    ),
    "title.community": (
        "Comunidad — Dabot", "Community — Dabot", "Communauté — Dabot", "Community — Dabot",
        "Comunidade — Dabot", "Community — Dabot", "コミュニティ — Dabot", "커뮤니티 — Dabot", "社区 — Dabot",
    ),
    "title.levels": (
        "Niveles — Dabot", "Levels — Dabot", "Niveaux — Dabot", "Level — Dabot",
        "Níveis — Dabot", "Livelli — Dabot", "レベル — Dabot", "레벨 — Dabot", "等级 — Dabot",
    ),
    "title.rules": (
        "Normas — Dabot", "Rules — Dabot", "Règles — Dabot", "Regeln — Dabot",
        "Normas — Dabot", "Regole — Dabot", "ルール — Dabot", "규칙 — Dabot", "规范 — Dabot",
    ),
    "title.verify": (
        "Verificación — Dabot", "Verification — Dabot", "Vérification — Dabot", "Verifizierung — Dabot",
        "Verificação — Dabot", "Verifica — Dabot", "認証 — Dabot", "인증 — Dabot", "验证 — Dabot",
    ),
    "title.help": (
        "Dabot - Centro de Ayuda & Comandos",
        "Dabot - Help & Commands",
        "Dabot - Aide & Commandes",
        "Dabot - Hilfe & Befehle",
        "Dabot - Ajuda & Comandos",
        "Dabot - Aiuto & Comandi",
        "Dabot - ヘルプとコマンド",
        "Dabot - 도움말 및 명령",
        "Dabot - 帮助与命令",
    ),
    "title.dashboard": (
        "Panel — Dabot", "Dashboard — Dabot", "Panel — Dabot", "Panel — Dabot",
        "Painel — Dabot", "Pannello — Dabot", "パネル — Dabot", "패널 — Dabot", "面板 — Dabot",
    ),
    "title.account": (
        "Cuenta — Dabot", "Account — Dabot", "Compte — Dabot", "Konto — Dabot",
        "Conta — Dabot", "Account — Dabot", "アカウント — Dabot", "계정 — Dabot", "账户 — Dabot",
    ),

    # Privacy body
    "pr.intro": (
        "Dabot es un bot de Discord y un panel web. Recogemos el mínimo de datos para que el bot funcione en tu servidor.",
        "Dabot is a Discord bot and a web panel. We collect the minimum data needed for the bot to work on your server.",
        "Dabot est un bot Discord et un panneau web. Nous collectons le minimum de données pour que le bot fonctionne sur ton serveur.",
        "Dabot ist ein Discord-Bot und ein Web-Panel. Wir erheben nur die Mindestdaten, damit der Bot auf deinem Server funktioniert.",
        "O Dabot é um bot de Discord e um painel web. Recolhemos o mínimo de dados para o bot funcionar no teu servidor.",
        "Dabot è un bot Discord e un pannello web. Raccogliamo il minimo di dati perché il bot funzioni sul tuo server.",
        "Dabot は Discord ボットと Web パネルです。ボットがサーバーで動くために必要な最小限のデータだけを収集します。",
        "Dabot은 Discord 봇이자 웹 패널입니다. 봇이 서버에서 작동하는 데 필요한 최소 데이터만 수집합니다.",
        "Dabot 是 Discord 机器人与网页面板。我们只收集机器人在你服务器上运行所需的最少数据。",
    ),
    "pr.h.store": (
        "Qué se guarda", "What we store", "Ce qui est conservé", "Was gespeichert wird",
        "O que é guardado", "Cosa viene salvato", "保存する内容", "저장되는 내용", "保存的内容",
    ),
    "pr.li.ids": (
        "IDs de Discord de usuarios, roles, canales y servidores donde el bot está invitado.",
        "Discord IDs of users, roles, channels and servers where the bot is invited.",
        "IDs Discord des utilisateurs, rôles, salons et serveurs où le bot est invité.",
        "Discord-IDs von Nutzern, Rollen, Kanälen und Servern, in denen der Bot eingeladen ist.",
        "IDs de Discord de utilizadores, cargos, canais e servidores onde o bot está convidado.",
        "ID Discord di utenti, ruoli, canali e server in cui il bot è invitato.",
        "ボットが招待されているユーザー・ロール・チャンネル・サーバーの Discord ID。",
        "봇이 초대된 사용자, 역할, 채널, 서버의 Discord ID.",
        "机器人所在服务器中的用户、身份组、频道与服务器的 Discord ID。",
    ),
    "pr.li.content": (
        "Contenido necesario para funciones que tú activas: infracciones, XP, economía, tickets, sugerencias, recordatorios, mensajes de bienvenida y, si usas el chatbot, fragmentos de conversación y memorias que un usuario pide recordar.",
        "Content needed for features you enable: infractions, XP, economy, tickets, suggestions, reminders, welcome messages and, if you use the chatbot, conversation snippets and memories a user asks to keep.",
        "Contenu nécessaire aux fonctions que tu actives : infractions, XP, économie, tickets, suggestions, rappels, messages de bienvenue et, si tu utilises le chatbot, extraits de conversation et souvenirs qu'un utilisateur demande de garder.",
        "Inhalt für Funktionen, die du aktivierst: Verstöße, XP, Wirtschaft, Tickets, Vorschläge, Erinnerungen, Willkommensnachrichten und — wenn du den Chatbot nutzt — Gesprächsausschnitte und Erinnerungen, die ein Nutzer speichern lässt.",
        "Conteúdo necessário para funções que ativas: infrações, XP, economia, tickets, sugestões, lembretes, mensagens de boas-vindas e, se usares o chatbot, excertos de conversa e memórias que um utilizador peça para guardar.",
        "Contenuto necessario alle funzioni che attivi: infrazioni, XP, economia, ticket, suggerimenti, promemoria, messaggi di benvenuto e, se usi il chatbot, frammenti di conversazione e memorie che un utente chiede di ricordare.",
        "有効にした機能に必要な内容：違反、XP、経済、チケット、提案、リマインダー、歓迎メッセージ、およびチャットボット利用時の会話断片とユーザーが記憶を依頼した内容。",
        "활성화한 기능에 필요한 내용: 제재, XP, 경제, 티켓, 제안, 알림, 환영 메시지, 챗봇 사용 시 대화 조각과 사용자가 기억해 달라고 한 내용.",
        "你启用的功能所需内容：违规、XP、经济、工单、建议、提醒、欢迎消息；若使用聊天机器人，还有对话片段及用户要求记住的内容。",
    ),
    "pr.li.panel": (
        "Panel web: sesión OAuth (identificador, nombre, avatar y token de acceso de Discord) durante 7 días.",
        "Web panel: OAuth session (Discord id, name, avatar and access token) for 7 days.",
        "Panneau web : session OAuth (identifiant, nom, avatar et jeton d'accès Discord) pendant 7 jours.",
        "Web-Panel: OAuth-Sitzung (Discord-ID, Name, Avatar und Zugriffstoken) für 7 Tage.",
        "Painel web: sessão OAuth (identificador, nome, avatar e token de acesso do Discord) durante 7 dias.",
        "Pannello web: sessione OAuth (identificativo, nome, avatar e token di accesso Discord) per 7 giorni.",
        "Webパネル：OAuth セッション（Discord の ID・名前・アバター・アクセストークン）を 7 日間。",
        "웹 패널: OAuth 세션(Discord ID, 이름, 아바타, 액세스 토큰) 7일.",
        "网页面板：OAuth 会话（Discord 标识、名称、头像与访问令牌）保留 7 天。",
    ),
    "pr.li.verify": (
        "Verificación / anti-multicuenta: si un servidor activa la verificación web se registran señales de red y de dispositivo (hasheadas para el staff de ese servidor: códigos de coincidencia exacta y de subred). Las verificaciones por VPN, proxy, Tor o iCloud Private Relay se rechazan. El staff no ve direcciones IP en claro.",
        "Verification / anti-multi-account: if a server enables web verification, network and device signals are stored (hashed for that server's staff: exact-match and subnet codes). Verifications via VPN, proxy, Tor or iCloud Private Relay are rejected. Staff do not see plain IP addresses.",
        "Vérification / anti multi-comptes : si un serveur active la vérif web, des signaux réseau et appareil sont enregistrés (hachés pour le staff de ce serveur : codes de correspondance exacte et de sous-réseau). VPN, proxy, Tor ou iCloud Private Relay sont refusés. Le staff ne voit pas les IP en clair.",
        "Verifizierung / Anti-Mehrfachkonten: aktiviert ein Server die Web-Verifizierung, werden Netz- und Gerätesignale gespeichert (gehasht für das Staff-Team: Exact-Match- und Subnetz-Codes). VPN, Proxy, Tor oder iCloud Private Relay werden abgelehnt. Staff sieht keine Klartext-IPs.",
        "Verificação / anti-multiconta: se um servidor ativa a verificação web, registam-se sinais de rede e dispositivo (hasheados para o staff desse servidor: códigos de correspondência exata e de sub-rede). VPN, proxy, Tor ou iCloud Private Relay são rejeitados. O staff não vê IPs em claro.",
        "Verifica / anti multi-account: se un server attiva la verifica web, vengono registrati segnali di rete e dispositivo (hash per lo staff di quel server: codici di corrispondenza esatta e di subnet). VPN, proxy, Tor o iCloud Private Relay vengono rifiutati. Lo staff non vede IP in chiaro.",
        "認証 / 複数アカウント対策：サーバーが Web 認証を有効にすると、ネットワークと端末の信号を記録します（そのサーバーのスタッフ向けにハッシュ化：完全一致とサブネットのコード）。VPN・プロキシ・Tor・iCloud Private Relay は拒否。スタッフは平文 IP を見ません。",
        "인증 / 다중계정 방지: 서버가 웹 인증을 켜면 네트워크·기기 신호가 저장됩니다(해당 서버 스태프용 해시: 정확 일치·서브넷 코드). VPN, 프록시, Tor, iCloud Private Relay는 거부됩니다. 스태프는 평문 IP를 보지 않습니다.",
        "验证 / 反多账号：若服务器启用网页验证，会记录网络与设备信号（对该服务器管理组哈希存储：精确匹配与子网代码）。通过 VPN、代理、Tor 或 iCloud Private Relay 的验证会被拒绝。管理组看不到明文 IP。",
    ),
    "pr.li.logs": (
        "Logs opcionales (mensajes borrados/editados) solo si un administrador configura un canal de auditoría.",
        "Optional logs (deleted/edited messages) only if an admin sets an audit channel.",
        "Journaux optionnels (messages supprimés/modifiés) seulement si un admin configure un salon d'audit.",
        "Optionale Logs (gelöschte/bearbeitete Nachrichten) nur wenn ein Admin einen Audit-Kanal setzt.",
        "Logs opcionais (mensagens apagadas/editadas) só se um admin configurar um canal de auditoria.",
        "Log opzionali (messaggi eliminati/modificati) solo se un admin configura un canale di audit.",
        "任意ログ（削除/編集されたメッセージ）は、管理者が監査チャンネルを設定した場合のみ。",
        "선택 로그(삭제/수정된 메시지)는 관리자가 감사 채널을 설정한 경우에만.",
        "可选日志（已删除/编辑的消息）仅在管理员配置审计频道时启用。",
    ),
    "pr.h.not": (
        "Qué no hacemos", "What we don't do", "Ce que nous ne faisons pas", "Was wir nicht tun",
        "O que não fazemos", "Cosa non facciamo", "しないこと", "하지 않는 일", "我们不会做的事",
    ),
    "pr.li.nosell": (
        "No vendemos datos. No hacemos publicidad con tu servidor.",
        "We don't sell data. We don't advertise with your server.",
        "Nous ne vendons pas de données. Pas de pub avec ton serveur.",
        "Wir verkaufen keine Daten. Keine Werbung mit deinem Server.",
        "Não vendemos dados. Não fazemos publicidade com o teu servidor.",
        "Non vendiamo dati. Niente pubblicità con il tuo server.",
        "データを販売しません。サーバーを使った広告もしません。",
        "데이터를 판매하지 않습니다. 서버로 광고하지 않습니다.",
        "我们不出售数据。不会用你的服务器做广告。",
    ),
    "pr.li.noread": (
        "No leemos el historial completo de un servidor salvo los módulos que el staff activa (IA, logs, niveles).",
        "We don't read a server's full history except for modules staff enable (AI, logs, levels).",
        "Nous ne lisons pas tout l'historique d'un serveur sauf les modules activés par le staff (IA, logs, niveaux).",
        "Wir lesen nicht die gesamte Server-Historie, außer Module, die das Team aktiviert (KI, Logs, Level).",
        "Não lemos o histórico completo de um servidor exceto os módulos que o staff ativa (IA, logs, níveis).",
        "Non leggiamo l'intera cronologia di un server salvo i moduli attivati dallo staff (IA, log, livelli).",
        "スタッフが有効にしたモジュール（AI、ログ、レベル）以外に、サーバーの全履歴は読みません。",
        "스태프가 켠 모듈(AI, 로그, 레벨) 외에는 서버 전체 기록을 읽지 않습니다.",
        "除管理组启用的模块（AI、日志、等级）外，我们不会读取服务器完整历史。",
    ),
    "pr.li.scopes": (
        "El panel no pide el scope de mensajes; solo identify y guilds.",
        "The panel does not request the messages scope; only identify and guilds.",
        "Le panneau ne demande pas le scope messages ; seulement identify et guilds.",
        "Das Panel fordert keinen messages-Scope; nur identify und guilds.",
        "O painel não pede o scope de mensagens; só identify e guilds.",
        "Il pannello non chiede lo scope messages; solo identify e guilds.",
        "パネルは messages スコープを要求しません。identify と guilds のみです。",
        "패널은 messages 스코프를 요청하지 않습니다. identify와 guilds만 사용합니다.",
        "面板不请求 messages 权限范围；仅使用 identify 与 guilds。",
    ),
    "pr.h.third": (
        "Terceros", "Third parties", "Tiers", "Drittanbieter", "Terceiros", "Terze parti", "第三者", "제3자", "第三方",
    ),
    "pr.third": (
        "Discord (API). Proveedores de IA que el bot use cuando alguien menciona a Dabot o lanza comandos de IA (el texto enviado es el del comando o la mención). Alojamiento en el VPS de davito.es.",
        "Discord (API). AI providers the bot uses when someone mentions Dabot or runs AI commands (the text sent is the command or mention). Hosting on the davito.es VPS.",
        "Discord (API). Fournisseurs d'IA utilisés quand quelqu'un mentionne Dabot ou lance des commandes IA (le texte envoyé est celui de la commande ou de la mention). Hébergement sur le VPS de davito.es.",
        "Discord (API). KI-Anbieter, die der Bot nutzt, wenn jemand Dabot erwähnt oder KI-Befehle startet (gesendet wird der Befehl-/Erwähnungstext). Hosting auf dem VPS von davito.es.",
        "Discord (API). Fornecedores de IA que o bot usa quando alguém menciona o Dabot ou corre comandos de IA (o texto enviado é o do comando ou da menção). Alojamento no VPS de davito.es.",
        "Discord (API). Provider IA usati quando qualcuno menziona Dabot o lancia comandi IA (il testo inviato è quello del comando o della menzione). Hosting sul VPS di davito.es.",
        "Discord（API）。誰かが Dabot をメンションしたり AI コマンドを実行したときに使う AI プロバイダ（送信テキストはコマンドまたはメンション）。ホスティングは davito.es の VPS。",
        "Discord(API). 누군가 Dabot을 멘션하거나 AI 명령을 실행할 때 사용하는 AI 제공자(전송 텍스트는 명령/멘션). 호스팅은 davito.es VPS.",
        "Discord（API）。有人提及 Dabot 或运行 AI 命令时使用的 AI 提供商（发送的文本为命令或提及内容）。托管在 davito.es 的 VPS。",
    ),
    "pr.h.retention": (
        "Conservación y baja", "Retention and deletion", "Conservation et suppression", "Aufbewahrung und Löschung",
        "Conservação e eliminação", "Conservazione e cancellazione", "保存と削除", "보관 및 삭제", "保留与删除",
    ),
    "pr.retention": (
        "Si expulsas al bot, puedes pedir el borrado de los datos de ese servidor escribiendo a Davito desde davito.es. Las sesiones web caducan a los 7 días o al pulsar Cerrar sesión.",
        "If you kick the bot, you can request deletion of that server's data by contacting Davito via davito.es. Web sessions expire after 7 days or when you log out.",
        "Si tu expulses le bot, tu peux demander l'effacement des données de ce serveur en écrivant à Davito via davito.es. Les sessions web expirent après 7 jours ou à la déconnexion.",
        "Wenn du den Bot entfernst, kannst du die Löschung der Serverdaten über Davito auf davito.es anfordern. Web-Sitzungen enden nach 7 Tagen oder beim Abmelden.",
        "Se expulsaves o bot, podes pedir o apagamento dos dados desse servidor contactando Davito em davito.es. As sessões web caducam aos 7 dias ou ao terminares sessão.",
        "Se espelli il bot, puoi chiedere la cancellazione dei dati di quel server scrivendo a Davito su davito.es. Le sessioni web scadono dopo 7 giorni o al logout.",
        "ボットを追放した場合、davito.es から Davito に連絡してそのサーバーのデータの削除を依頼できます。Web セッションは 7 日後またはログアウトで終了します。",
        "봇을 추방하면 davito.es에서 Davito에게 연락해 해당 서버 데이터 삭제를 요청할 수 있습니다. 웹 세션은 7일 후 또는 로그아웃 시 만료됩니다.",
        "若你踢出机器人，可通过 davito.es 联系 Davito 请求删除该服务器数据。网页会话在 7 天后或点击退出时失效。",
    ),
    "pr.h.minors": (
        "Menores", "Minors", "Mineurs", "Minderjährige", "Menores", "Minorenni", "未成年", "미성년자", "未成年人",
    ),
    "pr.minors": (
        "Dabot no está pensado para recoger datos de menores de 13 años. Cumple las reglas de Discord sobre contenido; los comandos slash públicos no incluyen nombres sexualmente explícitos.",
        "Dabot is not intended to collect data from children under 13. It follows Discord content rules; public slash command names are not sexually explicit.",
        "Dabot n'est pas conçu pour collecter des données de moins de 13 ans. Il respecte les règles de contenu Discord ; les noms de slash publics ne sont pas sexuellement explicites.",
        "Dabot ist nicht dafür gedacht, Daten von unter 13-Jährigen zu erheben. Es folgt Discords Inhaltsregeln; öffentliche Slash-Namen sind nicht sexuell explizit.",
        "O Dabot não se destina a recolher dados de menores de 13 anos. Cumpre as regras de conteúdo do Discord; os nomes de slash públicos não são sexualmente explícitos.",
        "Dabot non è pensato per raccogliere dati di minori di 13 anni. Rispetta le regole sui contenuti di Discord; i nomi slash pubblici non sono sessualmente espliciti.",
        "Dabot は 13 歳未満のデータの収集を想定していません。Discord のコンテンツルールに従い、公開スラッシュ名に性的に露骨なものはありません。",
        "Dabot은 13세 미만 데이터 수집을 목적으로 하지 않습니다. Discord 콘텐츠 규칙을 따르며, 공개 슬래시 이름에 성적으로 노골적인 표현이 없습니다.",
        "Dabot 无意收集 13 岁以下未成年人的数据。遵守 Discord 内容规则；公开斜杠命令名称不含露骨性内容。",
    ),
    "pr.contact": (
        "Contacto: a través de davito.es o el servidor de soporte del bot.",
        "Contact: via davito.es or the bot's support server.",
        "Contact : via davito.es ou le serveur support du bot.",
        "Kontakt: über davito.es oder den Support-Server des Bots.",
        "Contacto: através de davito.es ou do servidor de suporte do bot.",
        "Contatto: tramite davito.es o il server di supporto del bot.",
        "連絡先：davito.es またはボットのサポートサーバー。",
        "연락: davito.es 또는 봇 지원 서버.",
        "联系：通过 davito.es 或机器人的支持服务器。",
    ),

    # Terms body
    "te.1": (
        "Dabot se ofrece «tal cual». Davito puede cambiar módulos, pausar el servicio o expulsar el bot de un servidor que abuse de él (raid, spam, malware).",
        "Dabot is provided “as is”. Davito may change modules, pause the service or remove the bot from a server that abuses it (raid, spam, malware).",
        "Dabot est fourni « tel quel ». Davito peut changer des modules, pauser le service ou retirer le bot d'un serveur qui en abuse (raid, spam, malware).",
        "Dabot wird „wie besehen“ bereitgestellt. Davito kann Module ändern, den Dienst pausieren oder den Bot von einem Server entfernen, der ihn missbraucht (Raid, Spam, Malware).",
        "O Dabot é fornecido «tal como está». O Davito pode alterar módulos, pausar o serviço ou expulsar o bot de um servidor que abuse dele (raid, spam, malware).",
        "Dabot è fornito «così com'è». Davito può cambiare moduli, sospendere il servizio o rimuovere il bot da un server che ne abusa (raid, spam, malware).",
        "Dabot は現状有姿で提供されます。Davito はモジュール変更、サービス停止、乱用サーバーからの追放ができます（レイド、スパム、マルウェア）。",
        "Dabot은 «있는 그대로» 제공됩니다. Davito는 모듈 변경, 서비스 일시 중지, 남용 서버에서 봇 추방을 할 수 있습니다(레이드, 스팸, 멀웨어).",
        "Dabot 按「现状」提供。Davito 可更改模块、暂停服务，或将机器人从滥用的服务器中移除（突袭、垃圾信息、恶意软件）。",
    ),
    "te.2": (
        "Tú eres responsable de los permisos que otorgas al bot y de cumplir las condiciones de Discord.",
        "You are responsible for the permissions you grant the bot and for following Discord's terms.",
        "Tu es responsable des permissions que tu donnes au bot et du respect des conditions de Discord.",
        "Du bist für die Rechte verantwortlich, die du dem Bot gibst, und für die Einhaltung der Discord-Bedingungen.",
        "És responsável pelas permissões que dás ao bot e por cumprir as condições do Discord.",
        "Sei responsabile dei permessi che concedi al bot e del rispetto dei termini di Discord.",
        "ボットに与える権限と Discord の利用規約の遵守はあなたの責任です。",
        "봇에 부여하는 권한과 Discord 약관 준수는 당신의 책임입니다.",
        "你须对授予机器人的权限负责，并遵守 Discord 条款。",
    ),
    "te.3": (
        "Funciones Premium (copias de seguridad de estructura, IA extendida) pueden requerir suscripción. No hay reembolsos automáticos salvo lo que exija la ley.",
        "Premium features (structure backups, extended AI) may require a subscription. No automatic refunds except where the law requires.",
        "Les fonctions Premium (sauvegardes de structure, IA étendue) peuvent nécessiter un abonnement. Pas de remboursements automatiques sauf obligation légale.",
        "Premium-Funktionen (Struktur-Backups, erweiterte KI) können ein Abo erfordern. Keine automatischen Erstattungen außer gesetzlich vorgeschrieben.",
        "Funções Premium (backups de estrutura, IA alargada) podem exigir subscrição. Sem reembolsos automáticos salvo o que a lei exigir.",
        "Le funzioni Premium (backup di struttura, IA estesa) possono richiedere un abbonamento. Nessun rimborso automatico salvo obblighi di legge.",
        "Premium 機能（構造バックアップ、拡張 AI）にはサブスクが必要な場合があります。法令で求められる場合を除き自動返金はありません。",
        "Premium 기능(구조 백업, 확장 AI)은 구독이 필요할 수 있습니다. 법이 요구하는 경우를 제외하고 자동 환불은 없습니다.",
        "Premium 功能（结构备份、扩展 AI）可能需要订阅。除法律要求外，无自动退款。",
    ),
    "te.4": (
        "No uses Dabot para acoso, contenido ilegal o evadir las reglas de Discord. El operador puede borrar datos o denegar el servicio.",
        "Do not use Dabot for harassment, illegal content or to evade Discord rules. The operator may delete data or deny service.",
        "N'utilise pas Dabot pour du harcèlement, du contenu illégal ou pour contourner les règles Discord. L'opérateur peut effacer des données ou refuser le service.",
        "Nutze Dabot nicht für Belästigung, illegale Inhalte oder zum Umgehen von Discord-Regeln. Der Betreiber kann Daten löschen oder den Dienst verweigern.",
        "Não uses o Dabot para assédio, conteúdo ilegal ou para contornar as regras do Discord. O operador pode apagar dados ou recusar o serviço.",
        "Non usare Dabot per molestie, contenuti illegali o per eludere le regole di Discord. L'operatore può cancellare dati o negare il servizio.",
        "Dabot を嫌がらせ、違法コンテンツ、Discord ルール回避に使わないでください。運営はデータの削除やサービス拒否ができます。",
        "괴롭힘, 불법 콘텐츠, Discord 규칙 회피에 Dabot을 쓰지 마세요. 운영자는 데이터를 삭제하거나 서비스를 거부할 수 있습니다.",
        "请勿将 Dabot 用于骚扰、非法内容或规避 Discord 规则。运营方可删除数据或拒绝服务。",
    ),
    "te.5": (
        "El panel web es solo para quien tenga permiso de gestionar el servidor o un rol de staff asignado.",
        "The web panel is only for people who can manage the server or have an assigned staff role.",
        "Le panneau web est réservé à ceux qui peuvent gérer le serveur ou ont un rôle staff assigné.",
        "Das Web-Panel ist nur für Personen mit Server-Verwaltungsrechten oder zugewiesener Staff-Rolle.",
        "O painel web é só para quem puder gerir o servidor ou tiver um cargo de staff atribuído.",
        "Il pannello web è solo per chi può gestire il server o ha un ruolo staff assegnato.",
        "Web パネルはサーバー管理権限または割り当てられたスタッフロールがある人だけです。",
        "웹 패널은 서버를 관리할 수 있거나 지정된 스태프 역할이 있는 사람만 사용할 수 있습니다.",
        "网页面板仅供有服务器管理权限或已分配管理组身份组的人使用。",
    ),
    "te.6": (
        "La verificación web registra señales anti-abuso (dispositivo, navegador y códigos de red) para el staff de ese servidor. Compartir inteligencia entre servidores requiere aprobación expresa del operador de Dabot.",
        "Web verification stores anti-abuse signals (device, browser and network codes) for that server's staff. Sharing intelligence across servers needs explicit approval from Dabot's operator.",
        "La vérification web enregistre des signaux anti-abus (appareil, navigateur et codes réseau) pour le staff de ce serveur. Partager l'intelligence entre serveurs exige l'accord explicite de l'opérateur de Dabot.",
        "Die Web-Verifizierung speichert Anti-Missbrauch-Signale (Gerät, Browser und Netzcodes) für das Staff dieses Servers. Teilen von Intelligenz zwischen Servern braucht ausdrückliche Freigabe durch den Dabot-Betreiber.",
        "A verificação web regista sinais antiabuso (dispositivo, navegador e códigos de rede) para o staff desse servidor. Partilhar inteligência entre servidores exige aprovação expressa do operador do Dabot.",
        "La verifica web registra segnali anti-abuso (dispositivo, browser e codici di rete) per lo staff di quel server. Condividere intelligence tra server richiede approvazione esplicita dell'operatore di Dabot.",
        "Web 認証は、そのサーバーのスタッフ向けに不正対策信号（端末・ブラウザ・ネットワークコード）を記録します。サーバー間での共有には Dabot 運営の明示的な承認が必要です。",
        "웹 인증은 해당 서버 스태프를 위해 악용 방지 신호(기기, 브라우저, 네트워크 코드)를 기록합니다. 서버 간 정보 공유에는 Dabot 운영자의 명시적 승인이 필요합니다.",
        "网页验证会为该服务器管理组记录反滥用信号（设备、浏览器与网络代码）。跨服务器共享情报需经 Dabot 运营方明确批准。",
    ),
    "te.7": (
        "Estos términos se interpretan junto a la política de privacidad.",
        "These terms are read together with the privacy policy.",
        "Ces conditions s'interprètent avec la politique de confidentialité.",
        "Diese Bedingungen gelten zusammen mit der Datenschutzerklärung.",
        "Estes termos interpretam-se juntamente com a política de privacidade.",
        "Questi termini si interpretano insieme all'informativa sulla privacy.",
        "本規約はプライバシーポリシーと合わせて解釈されます。",
        "본 약관은 개인정보 처리방침과 함께 해석됩니다.",
        "本条款与隐私政策一并解释。",
    ),
    "te.contact": (
        "Contacto: davito.es",
        "Contact: davito.es",
        "Contact : davito.es",
        "Kontakt: davito.es",
        "Contacto: davito.es",
        "Contatto: davito.es",
        "連絡先：davito.es",
        "연락: davito.es",
        "联系：davito.es",
    ),
    "te.discord_terms": (
        "condiciones de Discord",
        "Discord's terms",
        "conditions de Discord",
        "Discord-Bedingungen",
        "condições do Discord",
        "termini di Discord",
        "Discordの利用規約",
        "Discord 약관",
        "Discord 条款",
    ),
    "te.privacy_link": (
        "política de privacidad",
        "privacy policy",
        "politique de confidentialité",
        "Datenschutzerklärung",
        "política de privacidade",
        "informativa sulla privacy",
        "プライバシーポリシー",
        "개인정보 처리방침",
        "隐私政策",
    ),
}

# Continue in part 2 - premium, community, help, dash gaps, js strings
NEW.update({
    "pm.title": (
        "Dabot Premium 🦞", "Dabot Premium 🦞", "Dabot Premium 🦞", "Dabot Premium 🦞",
        "Dabot Premium 🦞", "Dabot Premium 🦞", "Dabot Premium 🦞", "Dabot Premium 🦞", "Dabot Premium 🦞",
    ),
    "pm.lead": (
        "El núcleo del bot es gratis. Premium desbloquea IA pesada, backups completos y personalización. El pago se confirma automáticamente.",
        "The bot core is free. Premium unlocks heavy AI, full backups and customisation. Payment confirms automatically.",
        "Le cœur du bot est gratuit. Premium débloque l'IA lourde, les sauvegardes complètes et la perso. Le paiement se confirme tout seul.",
        "Der Bot-Kern ist gratis. Premium schaltet schwere KI, volle Backups und Anpassung frei. Die Zahlung bestätigt sich automatisch.",
        "O núcleo do bot é grátis. O Premium desbloqueia IA pesada, backups completos e personalização. O pagamento confirma-se automaticamente.",
        "Il nucleo del bot è gratis. Premium sblocca IA pesante, backup completi e personalizzazione. Il pagamento si conferma da solo.",
        "ボットの中核は無料です。Premium は重い AI、完全バックアップ、カスタムを解放します。支払いは自動確認されます。",
        "봇 핵심은 무료입니다. Premium은 무거운 AI, 전체 백업, 맞춤 설정을 엽니다. 결제는 자동 확인됩니다.",
        "机器人核心免费。Premium 解锁重度 AI、完整备份与个性化。付款会自动确认。",
    ),
    "pm.free.h": (
        "Gratis en todos los servidores", "Free on every server", "Gratuit sur tous les serveurs", "Gratis auf allen Servern",
        "Grátis em todos os servidores", "Gratis su tutti i server", "全サーバーで無料", "모든 서버에서 무료", "所有服务器免费",
    ),
    "pm.free.1": (
        "Moderación, tickets (registro en esta web), verificación, multicuentas",
        "Moderation, tickets (logged on this site), verification, multi-accounts",
        "Modération, tickets (historiques sur ce site), vérification, multi-comptes",
        "Moderation, Tickets (Protokoll auf dieser Seite), Verifizierung, Mehrfachkonten",
        "Moderação, tickets (registo neste site), verificação, multicontas",
        "Moderazione, ticket (storico su questo sito), verifica, multi-account",
        "モデレーション、チケット（このサイトに記録）、認証、複数アカウント",
        "모더레이션, 티켓(이 사이트에 기록), 인증, 다중 계정",
        "审核、工单（记录在本站）、验证、多账号",
    ),
    "pm.free.2": (
        "Radar de cuentas hackeadas (imágenes de MrBeast / Nitro falso)",
        "Hacked-account radar (fake MrBeast / Nitro images)",
        "Radar de comptes piratés (images MrBeast / Nitro faux)",
        "Radar für gehackte Konten (fake MrBeast-/Nitro-Bilder)",
        "Radar de contas invadidas (imagens MrBeast / Nitro falsas)",
        "Radar account violati (immagini MrBeast / Nitro false)",
        "乗っ取りアカウントレーダー（偽 MrBeast / Nitro 画像）",
        "해킹 계정 레이더(가짜 MrBeast / Nitro 이미지)",
        "被盗账号雷达（假 MrBeast / Nitro 图片）",
    ),
    "pm.free.3": (
        "Niveles (servidor + global), economía, AutoMod, anti-raid",
        "Levels (server + global), economy, AutoMod, anti-raid",
        "Niveaux (serveur + global), économie, AutoMod, anti-raid",
        "Level (Server + global), Wirtschaft, AutoMod, Anti-Raid",
        "Níveis (servidor + global), economia, AutoMod, anti-raid",
        "Livelli (server + globale), economia, AutoMod, anti-raid",
        "レベル（サーバー＋グローバル）、経済、AutoMod、アンチレイド",
        "레벨(서버+글로벌), 경제, AutoMod, 안티레이드",
        "等级（服务器+全局）、经济、AutoMod、防突袭",
    ),
    "pm.free.4": (
        "Logs, panel web, plantillas, bienvenida",
        "Logs, web panel, templates, welcome",
        "Logs, panneau web, modèles, bienvenue",
        "Logs, Web-Panel, Vorlagen, Willkommen",
        "Logs, painel web, modelos, boas-vindas",
        "Log, pannello web, template, benvenuto",
        "ログ、Webパネル、テンプレート、歓迎",
        "로그, 웹 패널, 템플릿, 환영",
        "日志、网页面板、模板、欢迎",
    ),
    "pm.paid.h": (
        "Con Premium", "With Premium", "Avec Premium", "Mit Premium",
        "Com Premium", "Con Premium", "Premium で", "Premium으로", "开通 Premium",
    ),
    "pm.paid.1": (
        "Mencionar a Dabot para chatear con IA, /tldr, /aimod, dibujar, personalidad",
        "Mention Dabot to chat with AI, /tldr, /aimod, draw, personality",
        "Mentionner Dabot pour chatter avec l'IA, /tldr, /aimod, dessiner, personnalité",
        "Dabot erwähnen für KI-Chat, /tldr, /aimod, Zeichnen, Persönlichkeit",
        "Mencionar o Dabot para falar com IA, /tldr, /aimod, desenhar, personalidade",
        "Menzionare Dabot per chattare con l'IA, /tldr, /aimod, disegnare, personalità",
        "Dabot をメンションして AI チャット、/tldr、/aimod、描画、個性",
        "Dabot 멘션으로 AI 채팅, /tldr, /aimod, 그림, 성격",
        "提及 Dabot 与 AI 聊天，以及 /tldr、/aimod、绘图、人设",
    ),
    "pm.paid.2": (
        "Backups completos (mensajes, imágenes, roles)",
        "Full backups (messages, images, roles)",
        "Sauvegardes complètes (messages, images, rôles)",
        "Volle Backups (Nachrichten, Bilder, Rollen)",
        "Backups completos (mensagens, imagens, cargos)",
        "Backup completi (messaggi, immagini, ruoli)",
        "完全バックアップ（メッセージ、画像、ロール）",
        "전체 백업(메시지, 이미지, 역할)",
        "完整备份（消息、图片、身份组）",
    ),
    "pm.paid.3": (
        "Comandos personalizados, cartas de rango/bienvenida, nombre del bot",
        "Custom commands, rank/welcome cards, bot name",
        "Commandes perso, cartes de rang/bienvenue, nom du bot",
        "Eigene Befehle, Rang-/Willkommenskarten, Bot-Name",
        "Comandos personalizados, cartas de rank/boas-vindas, nome do bot",
        "Comandi personalizzati, card rank/benvenuto, nome del bot",
        "カスタムコマンド、ランク/歓迎カード、ボット名",
        "맞춤 명령, 랭크/환영 카드, 봇 이름",
        "自定义命令、等级/欢迎卡片、机器人名称",
    ),
    "pm.paid.4": (
        "Más notas privadas", "More private notes", "Plus de notes privées", "Mehr private Notizen",
        "Mais notas privadas", "Più note private", "より多くのプライベートメモ", "더 많은 비공개 메모", "更多私人备注",
    ),
    "pm.plans.h": (
        "Planes", "Plans", "Offres", "Pläne", "Planos", "Piani", "プラン", "요금제", "套餐",
    ),
    "pm.plan.month": (
        "Mensual · 5 €", "Monthly · €5", "Mensuel · 5 €", "Monatlich · 5 €",
        "Mensal · 5 €", "Mensile · 5 €", "月額 · 5 €", "월간 · 5 €", "月付 · 5 €",
    ),
    "pm.plan.month.d": (
        "30 días", "30 days", "30 jours", "30 Tage", "30 dias", "30 giorni", "30 日", "30일", "30 天",
    ),
    "pm.plan.year": (
        "Anual · 50 €", "Yearly · €50", "Annuel · 50 €", "Jährlich · 50 €",
        "Anual · 50 €", "Annuale · 50 €", "年額 · 50 €", "연간 · 50 €", "年付 · 50 €",
    ),
    "pm.plan.year.d": (
        "365 días", "365 days", "365 jours", "365 Tage", "365 dias", "365 giorni", "365 日", "365일", "365 天",
    ),
    "pm.plan.life": (
        "Vitalicio · 200 €", "Lifetime · €200", "À vie · 200 €", "Lebenslang · 200 €",
        "Vitalício · 200 €", "A vita · 200 €", "買い切り · 200 €", "평생 · 200 €", "终身 · 200 €",
    ),
    "pm.plan.life.d": (
        "no caduca", "never expires", "n'expire pas", "läuft nicht ab",
        "não caduca", "non scade", "期限なし", "만료 없음", "永不过期",
    ),
    "pm.choose": (
        "Elegir", "Choose", "Choisir", "Wählen", "Escolher", "Scegli", "選ぶ", "선택", "选择",
    ),
    "pm.server_selected": (
        "Servidor seleccionado", "Selected server", "Serveur sélectionné", "Ausgewählter Server",
        "Servidor selecionado", "Server selezionato", "選択中のサーバー", "선택된 서버", "已选服务器",
    ),
    "pm.server_help": (
        "Introduce este ID en el formulario de Stripe:",
        "Enter this ID in the Stripe form:",
        "Entre cet ID dans le formulaire Stripe :",
        "Gib diese ID im Stripe-Formular ein:",
        "Introduz este ID no formulário da Stripe:",
        "Inserisci questo ID nel modulo Stripe:",
        "この ID を Stripe フォームに入力してください:",
        "이 ID를 Stripe 양식에 입력하세요:",
        "请在 Stripe 表单中填写此 ID：",
    ),
    "pm.how.h": (
        "Cómo activarlo", "How to activate", "Comment l'activer", "So aktivierst du es",
        "Como ativar", "Come attivarlo", "有効化の手順", "활성화 방법", "如何开通",
    ),
    "pm.how.1": (
        "Elige un plan.", "Pick a plan.", "Choisis une offre.", "Wähle einen Plan.",
        "Escolhe um plano.", "Scegli un piano.", "プランを選びます。", "요금제를 고르세요.", "选择套餐。",
    ),
    "pm.how.2": (
        "Introduce el ID numérico del servidor Discord.",
        "Enter the Discord server's numeric ID.",
        "Entre l'ID numérique du serveur Discord.",
        "Gib die numerische Discord-Server-ID ein.",
        "Introduz o ID numérico do servidor Discord.",
        "Inserisci l'ID numerico del server Discord.",
        "Discord サーバーの数値 ID を入力します。",
        "Discord 서버 숫자 ID를 입력하세요.",
        "输入 Discord 服务器的数字 ID。",
    ),
    "pm.how.3": (
        "Completa el pago.", "Complete the payment.", "Finalise le paiement.", "Schließe die Zahlung ab.",
        "Conclui o pagamento.", "Completa il pagamento.", "支払いを完了します。", "결제를 완료하세요.", "完成付款。",
    ),
    "pm.how.4": (
        "El webhook activará Premium automáticamente.",
        "The webhook activates Premium automatically.",
        "Le webhook active Premium automatiquement.",
        "Der Webhook aktiviert Premium automatisch.",
        "O webhook ativa o Premium automaticamente.",
        "Il webhook attiva Premium automaticamente.",
        "Webhook が Premium を自動で有効にします。",
        "웹훅이 Premium을 자동으로 켭니다.",
        "Webhook 会自动开通 Premium。",
    ),
    "pm.status": (
        "En Discord: /premium status para ver si este servidor está activo.",
        "In Discord: /premium status to see if this server is active.",
        "Sur Discord : /premium status pour voir si ce serveur est actif.",
        "In Discord: /premium status, um zu sehen, ob dieser Server aktiv ist.",
        "No Discord: /premium status para ver se este servidor está ativo.",
        "Su Discord: /premium status per vedere se questo server è attivo.",
        "Discord で /premium status を使い、このサーバーが有効か確認できます。",
        "Discord에서 /premium status로 이 서버 활성 여부를 확인하세요.",
        "在 Discord 使用 /premium status 查看此服务器是否已开通。",
    ),
    "pm.contact": (
        "Contacto: davito.es", "Contact: davito.es", "Contact : davito.es", "Kontakt: davito.es",
        "Contacto: davito.es", "Contatto: davito.es", "連絡先：davito.es", "연락: davito.es", "联系：davito.es",
    ),

    "com.card1.cat": ("01 Esencial", "01 Essentials", "01 Essentiel", "01 Essenziell", "01 Essencial", "01 Essenziale", "01 基本", "01 기본", "01 必备"),
    "com.card1.h": ("Normas", "Rules", "Règles", "Regeln", "Normas", "Regole", "ルール", "규칙", "规范"),
    "com.card1.p": (
        "Convivencia, voz y motivos de sanción.",
        "Community life, voice and sanction reasons.",
        "Vivre-ensemble, vocal et motifs de sanction.",
        "Zusammenleben, Voice und Sanktionsgründe.",
        "Convívio, voz e motivos de sanção.",
        "Convivenza, voce e motivi di sanzione.",
        "共同生活、ボイス、制裁理由。",
        "공동생활, 음성, 제재 사유.",
        "相处规则、语音与处罚事由。",
    ),
    "com.card2.cat": ("02 Actividad", "02 Activity", "02 Activité", "02 Aktivität", "02 Atividade", "02 Attività", "02 アクティビティ", "02 활동", "02 活跃"),
    "com.card2.h": ("Niveles", "Levels", "Niveaux", "Level", "Níveis", "Livelli", "レベル", "레벨", "等级"),
    "com.card2.p": (
        "XP, ranking y tu posición.",
        "XP, rankings and your place.",
        "XP, classements et ta place.",
        "XP, Ranglisten und dein Platz.",
        "XP, rankings e a tua posição.",
        "XP, classifiche e la tua posizione.",
        "XP、ランキング、あなたの順位。",
        "XP, 순위, 내 위치.",
        "XP、排行与你的位置。",
    ),
    "com.card3.cat": ("03 Moderación", "03 Moderation", "03 Modération", "03 Moderation", "03 Moderação", "03 Moderazione", "03 モデレーション", "03 모더레이션", "03 审核"),
    "com.card3.h": ("Apelaciones", "Appeals", "Appels", "Einsprüche", "Apelações", "Appelli", "異議申立", "이의신청", "申诉"),
    "com.card3.p": (
        "Tus casos y revisiones.",
        "Your cases and reviews.",
        "Tes dossiers et révisions.",
        "Deine Fälle und Prüfungen.",
        "Os teus casos e revisões.",
        "I tuoi casi e le revisioni.",
        "あなたの案件と見直し。",
        "내 사건과 재검토.",
        "你的案件与复核。",
    ),
    "com.card4.cat": ("04 Equipo", "04 Team", "04 Équipe", "04 Team", "04 Equipa", "04 Team", "04 チーム", "04 팀", "04 团队"),
    "com.card4.h": ("Staff", "Staff", "Staff", "Staff", "Staff", "Staff", "スタッフ", "스태프", "管理组"),
    "com.card4.p": (
        "Mesa de moderación y Discord.",
        "Moderation desk and Discord.",
        "Bureau de modération et Discord.",
        "Moderations-Tisch und Discord.",
        "Mesa de moderação e Discord.",
        "Tavolo di moderazione e Discord.",
        "モデレーションデスクと Discord。",
        "모더레이션 데스크와 Discord.",
        "审核台与 Discord。",
    ),

    "help.cat.ai": ("Inteligencia Artificial", "Artificial Intelligence", "Intelligence artificielle", "Künstliche Intelligenz", "Inteligência Artificial", "Intelligenza artificiale", "人工知能", "인공지능", "人工智能"),
    "help.cat.mod": ("Seguridad y Moderación", "Security & Moderation", "Sécurité et modération", "Sicherheit & Moderation", "Segurança e Moderação", "Sicurezza e moderazione", "セキュリティとモデレーション", "보안 및 모더레이션", "安全与审核"),
    "help.cat.level": ("Nivelación y Economía", "Leveling & Economy", "Niveaux et économie", "Level & Wirtschaft", "Níveis e Economia", "Livelli ed economia", "レベリングと経済", "레벨과 경제", "等级与经济"),
    "help.label.desc": ("Descripción:", "Description:", "Description :", "Beschreibung:", "Descrição:", "Descrizione:", "説明:", "설명:", "描述："),
    "help.label.syntax": ("Sintaxis:", "Syntax:", "Syntaxe :", "Syntax:", "Sintaxe:", "Sintassi:", "構文:", "구문:", "语法："),
    "help.label.perms": ("Permisos requeridos:", "Required permissions:", "Permissions requises :", "Erforderliche Rechte:", "Permissões necessárias:", "Permessi richiesti:", "必要な権限:", "필요 권한:", "所需权限："),
    "help.chat.short": ("Habla con el Chatbot de IA", "Talk to the AI chatbot", "Parle au chatbot IA", "Sprich mit dem KI-Chatbot", "Fala com o chatbot de IA", "Parla con il chatbot IA", "AI チャットボットと話す", "AI 챗봇과 대화", "与 AI 聊天机器人对话"),
    "help.chat.desc": (
        "Inicia una conversación interactiva con el bot usando Gemini o Groq. Posee memoria a largo plazo.",
        "Start an interactive chat with the bot using Gemini or Groq. It has long-term memory.",
        "Lance une conversation interactive avec le bot via Gemini ou Groq. Il a une mémoire long terme.",
        "Starte einen interaktiven Chat mit dem Bot über Gemini oder Groq. Er hat Langzeitgedächtnis.",
        "Inicia uma conversa interativa com o bot usando Gemini ou Groq. Tem memória de longo prazo.",
        "Avvia una chat interattiva con il bot usando Gemini o Groq. Ha memoria a lungo termine.",
        "Gemini または Groq でボットと対話します。長期記憶があります。",
        "Gemini 또는 Groq로 봇과 대화합니다. 장기 기억이 있습니다.",
        "使用 Gemini 或 Groq 与机器人互动聊天。具备长期记忆。",
    ),
    "help.chat.perms": (
        "Ninguno (Premium en mención directa).",
        "None (Premium for direct mentions).",
        "Aucun (Premium en mention directe).",
        "Keine (Premium bei direkter Erwähnung).",
        "Nenhum (Premium em menção direta).",
        "Nessuno (Premium in menzione diretta).",
        "なし（直接メンションは Premium）。",
        "없음(직접 멘션은 Premium).",
        "无（直接提及时需 Premium）。",
    ),
    "help.setpersonality.short": ("Cambia la personalidad de la IA", "Change the AI personality", "Change la personnalité de l'IA", "Ändert die KI-Persönlichkeit", "Muda a personalidade da IA", "Cambia la personalità dell'IA", "AI の個性を変更", "AI 성격 변경", "更改 AI 人设"),
    "help.setpersonality.desc": (
        "Configura un prompt del sistema personalizado para moldear la personalidad, tono y respuestas del bot en el servidor.",
        "Set a custom system prompt to shape the bot's personality, tone and replies on the server.",
        "Définis un prompt système perso pour façonner personnalité, ton et réponses du bot sur le serveur.",
        "Setzt einen eigenen System-Prompt, um Persönlichkeit, Ton und Antworten des Bots auf dem Server zu formen.",
        "Define um prompt de sistema personalizado para moldar personalidade, tom e respostas do bot no servidor.",
        "Imposta un prompt di sistema personalizzato per plasmare personalità, tono e risposte del bot sul server.",
        "サーバーでのボットの個性・口調・返答を形作るカスタムシステムプロンプトを設定します。",
        "서버에서 봇의 성격, 톤, 답변을 만드는 맞춤 시스템 프롬프트를 설정합니다.",
        "设置自定义系统提示词，塑造机器人在服务器中的人设、语气与回复。",
    ),
    "help.setpersonality.perms": ("Administrador (Premium).", "Administrator (Premium).", "Administrateur (Premium).", "Administrator (Premium).", "Administrador (Premium).", "Amministratore (Premium).", "管理者（Premium）。", "관리자(Premium).", "管理员（Premium）。"),
    "help.ban.short": ("Banea a un miembro", "Ban a member", "Bannit un membre", "Bannt ein Mitglied", "Ban a um membro", "Banna un membro", "メンバーをBAN", "멤버 차단", "封禁成员"),
    "help.ban.desc": (
        "Expulsa permanentemente a un usuario del servidor registrando la infracción.",
        "Permanently removes a user from the server and logs the infraction.",
        "Expulse définitivement un utilisateur du serveur en enregistrant l'infraction.",
        "Entfernt einen Nutzer dauerhaft vom Server und protokolliert den Verstoß.",
        "Expulsa permanentemente um utilizador do servidor e regista a infração.",
        "Rimuove definitivamente un utente dal server registrando l'infrazione.",
        "ユーザーをサーバーから永久に追放し、違反を記録します。",
        "사용자를 서버에서 영구 추방하고 위반을 기록합니다.",
        "永久将用户移出服务器并记录违规。",
    ),
    "help.ban.perms": ("Banear Miembros / Rol de Moderador.", "Ban Members / Moderator role.", "Bannir des membres / rôle modo.", "Mitglieder bannen / Mod-Rolle.", "Banir Membros / cargo de Moderador.", "Bannire membri / ruolo moderatore.", "メンバーのBAN / モデレーターロール。", "멤버 차단 / 모더레이터 역할.", "封禁成员 / 管理员身份组。"),
    "help.timeout.short": ("Aísla temporalmente a un miembro", "Temporarily isolate a member", "Isole temporairement un membre", "Isoliert ein Mitglied zeitweise", "Isola temporariamente um membro", "Isola temporaneamente un membro", "メンバーを一時隔離", "멤버를 일시 격리", "临时隔离成员"),
    "help.timeout.desc": (
        "Silencia a un usuario impidiéndole chatear o hablar en canales de voz por una duración específica.",
        "Mutes a user so they cannot chat or speak in voice for a set duration.",
        "Rend muet un utilisateur : plus de chat ni de vocal pendant une durée donnée.",
        "Stummschaltet einen Nutzer: kein Chat und kein Voice für eine festgelegte Dauer.",
        "Silencia um utilizador para não poder falar no chat ou na voz durante um período.",
        "Muta un utente impedendo chat e voce per una durata specifica.",
        "指定時間、チャットとボイスを使えなくします。",
        "정해진 시간 동안 채팅·음성을 못하게 음소거합니다.",
        "在指定时长内禁言，无法聊天或在语音频道说话。",
    ),
    "help.timeout.perms": ("Aislar Miembros / Rol de Moderador.", "Timeout Members / Moderator role.", "Mettre en sourdine / rôle modo.", "Mitglieder timeouten / Mod-Rolle.", "Isolar Membros / cargo de Moderador.", "Timeout membri / ruolo moderatore.", "メンバーのタイムアウト / モデレーターロール。", "멤버 타임아웃 / 모더레이터 역할.", "禁言成员 / 管理员身份组。"),
    "help.rank.short": ("Muestra el nivel de un usuario", "Show a user's level", "Affiche le niveau d'un utilisateur", "Zeigt das Level eines Nutzers", "Mostra o nível de um utilizador", "Mostra il livello di un utente", "ユーザーのレベルを表示", "사용자 레벨 표시", "显示用户等级"),
    "help.rank.desc": (
        "Obtén una tarjeta de perfil visual o texto indicando el nivel actual, XP total y porcentaje hacia el siguiente nivel.",
        "Get a visual or text profile card with current level, total XP and progress to the next level.",
        "Obtiens une carte profil (visuelle ou texte) avec niveau, XP total et progression vers le suivant.",
        "Holt eine Profilkarte (Bild oder Text) mit Level, Gesamt-XP und Fortschritt zum nächsten Level.",
        "Obtém um cartão de perfil (visual ou texto) com nível, XP total e progresso para o seguinte.",
        "Ottieni una card profilo (visiva o testo) con livello, XP totale e progresso al successivo.",
        "現在のレベル、総 XP、次レベルまでの進捗を示すプロフィールカード（画像またはテキスト）を取得します。",
        "현재 레벨, 총 XP, 다음 레벨 진행률이 있는 프로필 카드(이미지/텍스트)를 받습니다.",
        "获取含当前等级、总 XP 与距下一级进度的个人资料卡（图片或文字）。",
    ),
    "help.rank.perms": ("Ninguno.", "None.", "Aucun.", "Keine.", "Nenhum.", "Nessuno.", "なし。", "없음.", "无。"),
    "help.leaderboard.short": ("Clasificación del Servidor", "Server leaderboard", "Classement du serveur", "Server-Rangliste", "Classificação do servidor", "Classifica del server", "サーバーランキング", "서버 리더보드", "服务器排行榜"),
    "help.leaderboard.desc": (
        "Muestra el Top 10 de usuarios con mayor nivel del servidor actual.",
        "Shows the Top 10 highest-level users on the current server.",
        "Affiche le Top 10 des utilisateurs au plus haut niveau sur ce serveur.",
        "Zeigt die Top 10 Nutzer mit dem höchsten Level auf diesem Server.",
        "Mostra o Top 10 de utilizadores com maior nível neste servidor.",
        "Mostra la Top 10 degli utenti con il livello più alto su questo server.",
        "このサーバーでレベルが最も高いユーザー Top 10 を表示します。",
        "현재 서버에서 레벨이 가장 높은 사용자 Top 10을 보여줍니다.",
        "显示当前服务器等级最高的前 10 名用户。",
    ),
    "help.leaderboard.perms": ("Ninguno.", "None.", "Aucun.", "Keine.", "Nenhum.", "Nessuno.", "なし。", "없음.", "无。"),
    "help.footer": (
        "Desarrollado con ❤️ por Davito • Dabot © 2026",
        "Built with ❤️ by Davito • Dabot © 2026",
        "Développé avec ❤️ par Davito • Dabot © 2026",
        "Mit ❤️ von Davito • Dabot © 2026",
        "Desenvolvido com ❤️ por Davito • Dabot © 2026",
        "Sviluppato con ❤️ da Davito • Dabot © 2026",
        "Davito が ❤️ で開発 • Dabot © 2026",
        "Davito가 ❤️로 개발 • Dabot © 2026",
        "由 Davito 用 ❤️ 打造 • Dabot © 2026",
    ),
})

print("base NEW", len(NEW))

NEW.update({
    "dash.btn.welcome": ("Bienvenida", "Welcome", "Bienvenue", "Willkommen", "Boas-vindas", "Benvenuto", "歓迎", "환영", "欢迎"),
    "dash.btn.levels": ("Niveles", "Levels", "Niveaux", "Level", "Níveis", "Livelli", "レベル", "레벨", "等级"),
    "dash.filter.all_states": ("Todos los estados", "All statuses", "Tous les états", "Alle Status", "Todos os estados", "Tutti gli stati", "すべての状態", "모든 상태", "全部状态"),
    "dash.filter.all_methods": ("Todos los métodos", "All methods", "Toutes les méthodes", "Alle Methoden", "Todos os métodos", "Tutti i metodi", "すべての方法", "모든 방법", "全部方法"),
    "dash.filter.all_messages": ("Todos los mensajes", "All messages", "Tous les messages", "Alle Nachrichten", "Todas as mensagens", "Tutti i messaggi", "すべてのメッセージ", "모든 메시지", "全部消息"),
    "dash.logs.tickets_label": ("Tickets (nombre + enlace web)", "Tickets (name + web link)", "Tickets (nom + lien web)", "Tickets (Name + Web-Link)", "Tickets (nome + ligação web)", "Ticket (nome + link web)", "チケット（名前＋Webリンク）", "티켓(이름 + 웹 링크)", "工单（名称 + 网页链接）"),
    "dash.logs.verify_label": ("Verificaciones (quién se verifica)", "Verifications (who verifies)", "Vérifications (qui se vérifie)", "Verifizierungen (wer sich verifiziert)", "Verificações (quem se verifica)", "Verifiche (chi si verifica)", "認証（誰が認証するか）", "인증(누가 인증하는지)", "验证（谁完成验证）"),
    "dash.hijack.help": (
        "Imágenes de MrBeast / Nitro falso. No banea: silencia a la víctima y avisa al staff.",
        "Fake MrBeast / Nitro images. Does not ban: mutes the victim and alerts staff.",
        "Images MrBeast / Nitro faux. Ne ban pas : mute la victime et alerte le staff.",
        "Fake MrBeast-/Nitro-Bilder. Bannt nicht: stummschaltet das Opfer und warnt Staff.",
        "Imagens MrBeast / Nitro falsas. Não bane: silencia a vítima e avisa o staff.",
        "Immagini MrBeast / Nitro false. Non banna: muta la vittima e avvisa lo staff.",
        "偽 MrBeast / Nitro 画像。BAN せず被害者をミュートしスタッフに通知。",
        "가짜 MrBeast / Nitro 이미지. 차단하지 않고 피해자를 음소거하고 스태프에 알림.",
        "假 MrBeast / Nitro 图片。不封禁：禁言受害者并通知管理组。",
    ),
    "dash.admin.verifs.help": (
        "Todas las verificaciones de todos los servidores. Pulsa el # para ver IP completa, ISP, dispositivo, VPN y el resto de detalles. Solo tú ves esto.",
        "Every verification across all servers. Tap # for full IP, ISP, device, VPN and more. Only you see this.",
        "Toutes les vérifs de tous les serveurs. Tape # pour IP, FAI, appareil, VPN et plus. Toi seul vois ça.",
        "Alle Verifizierungen aller Server. Tippe # für volle IP, ISP, Gerät, VPN und mehr. Nur du siehst das.",
        "Todas as verificações de todos os servidores. Toca # para IP, ISP, dispositivo, VPN e mais. Só tu vês isto.",
        "Tutte le verifiche di tutti i server. Tocca # per IP, ISP, dispositivo, VPN e altro. Solo tu lo vedi.",
        "全サーバーの全認証。# で完全 IP・ISP・端末・VPN などを表示。あなただけが見られます。",
        "모든 서버의 모든 인증. #을 눌러 전체 IP, ISP, 기기, VPN 등을 봅니다. 당신만 볼 수 있습니다.",
        "所有服务器的全部验证。点 # 查看完整 IP、ISP、设备、VPN 等。仅你可见。",
    ),
    "dash.admin.premium.id_help": (
        "El ID es el snowflake del servidor o del usuario. Vitalicio no caduca.",
        "The ID is the server or user snowflake. Lifetime never expires.",
        "L'ID est le snowflake serveur ou utilisateur. À vie n'expire pas.",
        "Die ID ist die Server- oder Nutzer-Snowflake. Lebenslang läuft nicht ab.",
        "O ID é o snowflake do servidor ou do utilizador. Vitalício não caduca.",
        "L'ID è lo snowflake del server o dell'utente. A vita non scade.",
        "ID はサーバーまたはユーザーの snowflake。買い切りは期限なし。",
        "ID는 서버 또는 사용자 스노플레이크입니다. 평생은 만료되지 않습니다.",
        "ID 为服务器或用户的 snowflake。终身不过期。",
    ),
    "dash.admin.any_panel.help": (
        "Abre el panel de cualquiera. Configuración, Discord, sanciones, logs y verificación: tú tienes control total aunque no estés dentro del servidor.",
        "Open anyone's panel. Config, Discord, sanctions, logs and verification: full control even if you're not in the server.",
        "Ouvre le panneau de n'importe qui. Config, Discord, sanctions, logs et vérif : contrôle total même hors du serveur.",
        "Öffne jedes Panel. Config, Discord, Sanktionen, Logs und Verifizierung: volle Kontrolle auch ohne Server-Mitgliedschaft.",
        "Abre o painel de qualquer um. Config, Discord, sanções, logs e verificação: controlo total mesmo fora do servidor.",
        "Apri il pannello di chiunque. Config, Discord, sanzioni, log e verifica: controllo totale anche fuori dal server.",
        "誰のパネルでも開けます。設定・Discord・制裁・ログ・認証：サーバー外でも完全制御。",
        "아무 패널이나 엽니다. 설정, Discord, 제재, 로그, 인증: 서버 밖에서도 전체 제어.",
        "打开任何人的面板。配置、Discord、处罚、日志与验证：即使不在服务器内也有完全控制。",
    ),
    "dash.setup.gap.help": (
        "Lo que falta para que Dabot trabaje solo. Premium es opcional.",
        "What's left so Dabot can run on its own. Premium is optional.",
        "Ce qu'il manque pour que Dabot tourne seul. Premium est optionnel.",
        "Was noch fehlt, damit Dabot allein läuft. Premium ist optional.",
        "O que falta para o Dabot trabalhar sozinho. Premium é opcional.",
        "Ciò che manca perché Dabot lavori da solo. Premium è opzionale.",
        "Dabot が一人で動くために足りないもの。Premium は任意。",
        "Dabot이 혼자 일하도록 남은 것. Premium은 선택.",
        "让 Dabot 自行运转还缺什么。Premium 可选。",
    ),
    "dash.ticket.design.help": (
        "Diseña el panel (embeds, fotos de producto, desplegable) y publícalo. El historial de cada ticket vive aquí aunque se borre el canal.",
        "Design the panel (embeds, product photos, dropdown) and publish it. Each ticket's history stays here even if the channel is deleted.",
        "Conçois le panneau (embeds, photos produit, menu) et publie-le. L'historique de chaque ticket reste ici même si le salon est supprimé.",
        "Gestalte das Panel (Embeds, Produktfotos, Menü) und veröffentliche es. Die Ticket-Historie bleibt hier, auch wenn der Kanal gelöscht wird.",
        "Desenha o painel (embeds, fotos de produto, menu) e publica-o. O histórico de cada ticket fica aqui mesmo se o canal for apagado.",
        "Progetta il pannello (embed, foto prodotto, menu) e pubblicalo. Lo storico di ogni ticket resta qui anche se il canale viene eliminato.",
        "パネル（埋め込み、商品写真、ドロップダウン）を設計して公開。チャンネル削除後もチケット履歴はここに残ります。",
        "패널(임베드, 상품 사진, 드롭다운)을 디자인해 게시하세요. 채널이 삭제돼도 티켓 기록은 여기에 남습니다.",
        "设计面板（嵌入、产品图、下拉菜单）并发布。即使频道被删，工单历史仍保留在此。",
    ),
    "dash.ticket.embeds.help": (
        "El mensaje de Discord puede llevar hasta 10 embeds: portada + fichas de producto con imagen. El desplegable lista todas las opciones (máx. 125).",
        "The Discord message can carry up to 10 embeds: cover + product cards with images. The dropdown lists all options (max 125).",
        "Le message Discord peut avoir jusqu'à 10 embeds : couverture + fiches produit avec image. Le menu liste toutes les options (max 125).",
        "Die Discord-Nachricht kann bis zu 10 Embeds haben: Cover + Produktkarten mit Bild. Das Menü listet alle Optionen (max. 125).",
        "A mensagem Discord pode ter até 10 embeds: capa + fichas de produto com imagem. O menu lista todas as opções (máx. 125).",
        "Il messaggio Discord può avere fino a 10 embed: copertina + schede prodotto con immagine. Il menu elenca tutte le opzioni (max 125).",
        "Discord メッセージは最大 10 埋め込み：表紙＋画像付き商品カード。ドロップダウンは全オプション（最大 125）。",
        "Discord 메시지는 임베드 최대 10개: 표지 + 이미지 상품 카드. 드롭다운은 모든 옵션(최대 125).",
        "Discord 消息最多 10 个嵌入：封面 + 带图产品卡。下拉列出全部选项（最多 125）。",
    ),
    "dash.rules.publish.help": (
        "Esto se publica en dabot.davito.es/normas para este servidor.",
        "This is published at dabot.davito.es/normas for this server.",
        "Ça se publie sur dabot.davito.es/normas pour ce serveur.",
        "Das wird auf dabot.davito.es/normas für diesen Server veröffentlicht.",
        "Isto é publicado em dabot.davito.es/normas para este servidor.",
        "Questo viene pubblicato su dabot.davito.es/normas per questo server.",
        "このサーバー向けに dabot.davito.es/normas で公開されます。",
        "이 서버용으로 dabot.davito.es/normas에 게시됩니다.",
        "将发布到 dabot.davito.es/normas（本服务器）。",
    ),
    "dash.verify.people.help": (
        "Última verificación correcta de cada cuenta. Pulsa un ID para filtrar el historial.",
        "Latest successful verification per account. Tap an ID to filter history.",
        "Dernière vérif réussie par compte. Tape un ID pour filtrer l'historique.",
        "Letzte erfolgreiche Verifizierung je Konto. Tippe eine ID, um die Historie zu filtern.",
        "Última verificação correta de cada conta. Toca num ID para filtrar o histórico.",
        "Ultima verifica riuscita per account. Tocca un ID per filtrare lo storico.",
        "アカウントごとの最新の成功認証。ID を押すと履歴を絞り込み。",
        "계정별 최근 성공 인증. ID를 눌러 기록을 필터링하세요.",
        "每个账号最近一次成功验证。点 ID 可筛选历史。",
    ),
    "dash.verify.events.help": (
        "Cada intento: navegador, reto, staff o resolución de multicuenta.",
        "Each attempt: browser, challenge, staff or multi-account resolution.",
        "Chaque tentative : navigateur, défi, staff ou résolution multi-comptes.",
        "Jeder Versuch: Browser, Challenge, Staff oder Mehrfachkonto-Lösung.",
        "Cada tentativa: navegador, desafio, staff ou resolução de multiconta.",
        "Ogni tentativo: browser, sfida, staff o risoluzione multi-account.",
        "各試行：ブラウザ、チャレンジ、スタッフ、または複数アカウント解決。",
        "각 시도: 브라우저, 도전, 스태프 또는 다중계정 처리.",
        "每次尝试：浏览器、挑战、管理组或多账号处理。",
    ),
    "dash.option_n": ("Opción {n}", "Option {n}", "Option {n}", "Option {n}", "Opção {n}", "Opzione {n}", "オプション {n}", "옵션 {n}", "选项 {n}"),
    "dash.ticket.desc_label": ("Descripción (desplegable)", "Description (dropdown)", "Description (menu)", "Beschreibung (Menü)", "Descrição (menu)", "Descrizione (menu)", "説明（ドロップダウン）", "설명(드롭다운)", "描述（下拉）"),
    "dash.ticket.detail_label": ("Detalle (embed del producto / ticket)", "Detail (product / ticket embed)", "Détail (embed produit / ticket)", "Detail (Produkt-/Ticket-Embed)", "Detalhe (embed do produto / ticket)", "Dettaglio (embed prodotto / ticket)", "詳細（商品/チケット埋め込み）", "상세(상품/티켓 임베드)", "详情（产品/工单嵌入）"),
    "dash.active": ("activo", "active", "actif", "aktiv", "ativo", "attivo", "有効", "활성", "有效"),
    "dash.expired": ("caducado", "expired", "expiré", "abgelaufen", "caducado", "scaduto", "期限切れ", "만료", "已过期"),
    "dash.free_pill": ("gratis", "free", "gratuit", "gratis", "grátis", "gratis", "無料", "무료", "免费"),
    "dash.no_channel": ("Sin canal disponible", "No channel available", "Aucun salon disponible", "Kein Kanal verfügbar", "Sem canal disponível", "Nessun canale disponibile", "利用可能なチャンネルなし", "사용 가능한 채널 없음", "无可用频道"),
    "dash.now_channel": ("Ahora: #{name}", "Now: #{name}", "Maintenant : #{name}", "Jetzt: #{name}", "Agora: #{name}", "Ora: #{name}", "現在: #{name}", "지금: #{name}", "当前：#{name}"),
    "dash.bot_no_guilds": ("El bot no está en ningún servidor.", "The bot is in no servers.", "Le bot n'est sur aucun serveur.", "Der Bot ist auf keinem Server.", "O bot não está em nenhum servidor.", "Il bot non è in nessun server.", "ボットはどのサーバーにもいません。", "봇이 어떤 서버에도 없습니다.", "机器人不在任何服务器中。"),
    "dash.empty.session": ("No se pudo leer la sesión.", "Could not read the session.", "Impossible de lire la session.", "Sitzung konnte nicht gelesen werden.", "Não foi possível ler a sessão.", "Impossibile leggere la sessione.", "セッションを読めませんでした。", "세션을 읽지 못했습니다.", "无法读取会话。"),
    "dash.empty.disabled": ("Desactivado", "Disabled", "Désactivé", "Deaktiviert", "Desativado", "Disattivato", "無効", "꺼짐", "已关闭"),
    "dash.empty.select_role": ("Selecciona un rol…", "Select a role…", "Choisis un rôle…", "Rolle wählen…", "Seleciona um cargo…", "Seleziona un ruolo…", "ロールを選択…", "역할 선택…", "选择身份组…"),
    "dash.empty.xp": ("Sin XP todavía.", "No XP yet.", "Pas encore d'XP.", "Noch keine XP.", "Ainda sem XP.", "Ancora niente XP.", "まだ XP がありません。", "아직 XP가 없습니다.", "尚无 XP。"),
    "dash.empty.invites": ("Sin invitaciones trackeadas.", "No tracked invites.", "Aucune invitation suivie.", "Keine getrackten Einladungen.", "Sem convites seguidos.", "Nessun invito tracciato.", "追跡中の招待はありません。", "추적 중인 초대가 없습니다.", "没有跟踪中的邀请。"),
    "dash.empty.economy": ("Sin actividad económica todavía.", "No economy activity yet.", "Pas encore d'activité éco.", "Noch keine Wirtschaftsaktivität.", "Ainda sem atividade económica.", "Ancora nessuna attività economica.", "まだ経済活動がありません。", "아직 경제 활동이 없습니다.", "尚无经济活动。"),
    "dash.empty.infractions": ("Sin sanciones.", "No infractions.", "Aucune sanction.", "Keine Sanktionen.", "Sem sanções.", "Nessuna sanzione.", "制裁はありません。", "제재가 없습니다.", "没有处罚。"),
    "dash.empty.appeals": ("Sin apelaciones.", "No appeals.", "Aucun appel.", "Keine Einsprüche.", "Sem apelações.", "Nessun appello.", "異議はありません。", "이의신청이 없습니다.", "没有申诉。"),
    "dash.empty.loading": ("Cargando…", "Loading…", "Chargement…", "Laden…", "A carregar…", "Caricamento…", "読み込み中…", "로딩 중…", "加载中…"),
    "dash.empty.loading_id": ("Cargando #{id}…", "Loading #{id}…", "Chargement #{id}…", "Lade #{id}…", "A carregar #{id}…", "Caricamento #{id}…", "#{id} を読み込み中…", "#{id} 로딩 중…", "正在加载 #{id}…"),
    "dash.empty.messages": ("Sin mensajes guardados.", "No saved messages.", "Aucun message enregistré.", "Keine gespeicherten Nachrichten.", "Sem mensagens guardadas.", "Nessun messaggio salvato.", "保存されたメッセージはありません。", "저장된 메시지가 없습니다.", "没有已保存的消息。"),
    "dash.empty.open_fail": ("No se pudo abrir.", "Could not open.", "Impossible d'ouvrir.", "Konnte nicht öffnen.", "Não foi possível abrir.", "Impossibile aprire.", "開けませんでした。", "열 수 없습니다.", "无法打开。"),
    "dash.empty.channels": ("Sin canales.", "No channels.", "Aucun salon.", "Keine Kanäle.", "Sem canais.", "Nessun canale.", "チャンネルがありません。", "채널이 없습니다.", "没有频道。"),
    "dash.empty.templates": ("Cargando plantillas…", "Loading templates…", "Chargement des modèles…", "Vorlagen werden geladen…", "A carregar modelos…", "Caricamento template…", "テンプレート読み込み中…", "템플릿 로딩 중…", "正在加载模板…"),
    "dash.empty.logs": ("Aún no hay registros. Activa logs en Configuración o usa /log here.", "No logs yet. Enable logs in Settings or use /log here.", "Pas encore de journaux. Active-les dans Config ou /log here.", "Noch keine Logs. Aktiviere Logs in Einstellungen oder /log here.", "Ainda sem registos. Ativa logs em Definições ou /log here.", "Ancora nessun log. Attivali in Config o /log here.", "まだログがありません。設定で有効化するか /log here。", "아직 로그가 없습니다. 설정에서 켜거나 /log here.", "尚无日志。在设置中启用或使用 /log here。"),
    "dash.empty.alt_cases": ("Sin casos todavía. Aparecen cuando hay coincidencia en la verificación web.", "No cases yet. They appear when web verification matches.", "Pas encore de dossiers. Ils apparaissent quand la vérif web matche.", "Noch keine Fälle. Erscheinen bei Web-Verifizierungs-Treffern.", "Ainda sem casos. Aparecem com coincidência na verificação web.", "Ancora nessun caso. Compaino con match nella verifica web.", "まだ案件がありません。Web 認証の一致で表示されます。", "아직 사건이 없습니다. 웹 인증 일치 시 나타납니다.", "尚无案件。网页验证匹配时会出现。"),
    "dash.empty.alt_hits": ("Sin coincidencias todavía. La gente tiene que verificarse por el navegador.", "No matches yet. People must verify in the browser.", "Pas encore de correspondances. Il faut se vérifier dans le navigateur.", "Noch keine Treffer. Leute müssen sich im Browser verifizieren.", "Ainda sem coincidências. É preciso verificar no navegador.", "Ancora nessuna corrispondenza. Serve verificarsi nel browser.", "まだ一致がありません。ブラウザで認証が必要です。", "아직 일치가 없습니다. 브라우저에서 인증해야 합니다.", "尚无匹配。需要在浏览器中完成验证。"),
    "dash.empty.pending_none": ("No hay casos pendientes.", "No pending cases.", "Aucun dossier en attente.", "Keine offenen Fälle.", "Sem casos pendentes.", "Nessun caso in sospeso.", "保留中の案件はありません。", "대기 중인 사건이 없습니다.", "没有待处理案件。"),
    "dash.empty.filter_none": ("Sin casos con ese filtro.", "No cases for that filter.", "Aucun dossier pour ce filtre.", "Keine Fälle für diesen Filter.", "Sem casos com esse filtro.", "Nessun caso per quel filtro.", "そのフィルターの案件はありません。", "해당 필터의 사건이 없습니다.", "该筛选下没有案件。"),
    "dash.empty.nobody_verified": ("Nadie se ha verificado todavía. Tienen que pasar el panel o /verification manual.", "Nobody verified yet. They must use the panel or /verification manual.", "Personne n'est encore vérifié. Il faut le panneau ou /verification manual.", "Noch niemand verifiziert. Panel oder /verification manual nötig.", "Ninguém se verificou ainda. É preciso o painel ou /verification manual.", "Nessuno si è ancora verificato. Serve il pannello o /verification manual.", "まだ誰も認証していません。パネルか /verification manual が必要です。", "아직 아무도 인증하지 않았습니다. 패널 또는 /verification manual이 필요합니다.", "尚无人验证。需通过面板或 /verification manual。"),
    "dash.empty.no_events": ("Sin eventos. Cuando alguien se verifique, aparece aquí y en el canal de logs.", "No events. When someone verifies, it shows here and in the logs channel.", "Aucun événement. Quand quelqu'un se vérifie, ça apparaît ici et dans les logs.", "Keine Ereignisse. Bei Verifizierung erscheint es hier und im Log-Kanal.", "Sem eventos. Quando alguém se verificar, aparece aqui e nos logs.", "Nessun evento. Quando qualcuno si verifica, appare qui e nei log.", "イベントなし。認証するとこことログチャンネルに出ます。", "이벤트 없음. 누군가 인증하면 여기와 로그 채널에 표시됩니다.", "无事件。有人验证后会显示在这里和日志频道。"),
    "dash.empty.list_fail": ("No se pudo leer el listado.", "Could not read the list.", "Impossible de lire la liste.", "Liste konnte nicht gelesen werden.", "Não foi possível ler a lista.", "Impossibile leggere l'elenco.", "一覧を読めませんでした。", "목록을 읽지 못했습니다.", "无法读取列表。"),
    "dash.empty.history_fail": ("No se pudo leer el historial.", "Could not read the history.", "Impossible de lire l'historique.", "Historie konnte nicht gelesen werden.", "Não foi possível ler o histórico.", "Impossibile leggere lo storico.", "履歴を読めませんでした。", "기록을 읽지 못했습니다.", "无法读取历史。"),
    "dash.empty.verifs_filter": ("Sin verificaciones con ese filtro.", "No verifications for that filter.", "Aucune vérif pour ce filtre.", "Keine Verifizierungen für diesen Filter.", "Sem verificações com esse filtro.", "Nessuna verifica per quel filtro.", "そのフィルターの認証はありません。", "해당 필터의 인증이 없습니다.", "该筛选下没有验证。"),
    "dash.empty.verifs_fail": ("No se pudieron leer las verificaciones.", "Could not read verifications.", "Impossible de lire les vérifs.", "Verifizierungen konnten nicht gelesen werden.", "Não foi possível ler as verificações.", "Impossibile leggere le verifiche.", "認証を読めませんでした。", "인증을 읽지 못했습니다.", "无法读取验证。"),
    "dash.empty.detail_fail": ("No se pudo leer el detalle.", "Could not read the detail.", "Impossible de lire le détail.", "Detail konnte nicht gelesen werden.", "Não foi possível ler o detalhe.", "Impossibile leggere il dettaglio.", "詳細を読めませんでした。", "세부정보를 읽지 못했습니다.", "无法读取详情。"),
    "dash.empty.fingerprints": ("Sin huellas web. Pídele que abra la verificación del navegador.", "No web fingerprints. Ask them to open browser verification.", "Pas d'empreintes web. Demande d'ouvrir la vérif navigateur.", "Keine Web-Fingerprints. Bitte Browser-Verifizierung öffnen.", "Sem impressões web. Pede para abrir a verificação no navegador.", "Nessuna impronta web. Chiedi di aprire la verifica nel browser.", "Web 指紋がありません。ブラウザ認証を開くよう伝えてください。", "웹 지문이 없습니다. 브라우저 인증을 열어 달라고 하세요.", "没有网页指纹。请让对方打开浏览器验证。"),
    "dash.empty.load_fail": ("No se pudo cargar", "Could not load", "Impossible de charger", "Laden fehlgeschlagen", "Não foi possível carregar", "Impossibile caricare", "読み込めませんでした", "불러오지 못함", "无法加载"),
    "dash.empty.tickets_fail": ("No se pudieron leer los tickets.", "Could not read tickets.", "Impossible de lire les tickets.", "Tickets konnten nicht gelesen werden.", "Não foi possível ler os tickets.", "Impossibile leggere i ticket.", "チケットを読めませんでした。", "티켓을 읽지 못했습니다.", "无法读取工单。"),
    "dash.empty.premium_none": ("Ningún servidor premium aún.", "No premium servers yet.", "Aucun serveur premium encore.", "Noch keine Premium-Server.", "Ainda sem servidores premium.", "Ancora nessun server premium.", "まだ Premium サーバーがありません。", "아직 프리미엄 서버가 없습니다.", "尚无 Premium 服务器。"),
    "dash.verify.detail_title": ("Detalle verificación #{id}", "Verification detail #{id}", "Détail vérif #{id}", "Verifizierungsdetail #{id}", "Detalhe verificação #{id}", "Dettaglio verifica #{id}", "認証詳細 #{id}", "인증 상세 #{id}", "验证详情 #{id}"),
    "dash.verify.col.origin": ("Origen", "Origin", "Origine", "Ursprung", "Origem", "Origine", "送信元", "출처", "来源"),
    "dash.verify.col.client": ("Cliente", "Client", "Client", "Client", "Cliente", "Client", "クライアント", "클라이언트", "客户端"),
    "dash.verify.col.locale": ("Locale", "Locale", "Locale", "Locale", "Locale", "Locale", "ロケール", "로케일", "语言区域"),
    "dash.verify.col.ip": ("IP", "IP", "IP", "IP", "IP", "IP", "IP", "IP", "IP"),
    "dash.verify.field.exact": ("Código exacto (ip:)", "Exact code (ip:)", "Code exact (ip :)", "Exakter Code (ip:)", "Código exato (ip:)", "Codice esatto (ip:)", "完全一致コード (ip:)", "정확 코드 (ip:)", "精确代码 (ip:)"),
    "dash.verify.field.net": ("Código de red (net:)", "Network code (net:)", "Code réseau (net :)", "Netzcode (net:)", "Código de rede (net:)", "Codice di rete (net:)", "ネットコード (net:)", "네트워크 코드 (net:)", "网络代码 (net:)"),
    "dash.verify.field.country": ("País", "Country", "Pays", "Land", "País", "Paese", "国", "국가", "国家"),
    "dash.verify.yes": ("sí", "yes", "oui", "ja", "sim", "sì", "はい", "예", "是"),
    "dash.verify.no": ("no", "no", "non", "nein", "não", "no", "いいえ", "아니요", "否"),
    "dash.verify.vpn_yes": ("sí · {kinds}", "yes · {kinds}", "oui · {kinds}", "ja · {kinds}", "sim · {kinds}", "sì · {kinds}", "はい · {kinds}", "예 · {kinds}", "是 · {kinds}"),
    "dash.verify.hosting_line": (
        "{hosting} / {proxy} / móvil {mobile}",
        "{hosting} / {proxy} / mobile {mobile}",
        "{hosting} / {proxy} / mobile {mobile}",
        "{hosting} / {proxy} / mobil {mobile}",
        "{hosting} / {proxy} / móvel {mobile}",
        "{hosting} / {proxy} / mobile {mobile}",
        "{hosting} / {proxy} / モバイル {mobile}",
        "{hosting} / {proxy} / 모바일 {mobile}",
        "{hosting} / {proxy} / 移动 {mobile}",
    ),
    "dash.backup.in_progress": (
        "Copia completa en curso (mensajes, imágenes y roles)… recarga en un minuto.",
        "Full backup in progress (messages, images and roles)… reload in a minute.",
        "Sauvegarde complète en cours (messages, images et rôles)… recharge dans une minute.",
        "Vollbackup läuft (Nachrichten, Bilder und Rollen)… in einer Minute neu laden.",
        "Cópia completa em curso (mensagens, imagens e cargos)… recarrega num minuto.",
        "Backup completo in corso (messaggi, immagini e ruoli)… ricarica tra un minuto.",
        "完全バックアップ中（メッセージ・画像・ロール）…1分後に再読み込み。",
        "전체 백업 중(메시지, 이미지, 역할)…1분 후 새로고침.",
        "完整备份进行中（消息、图片与身份组）…一分钟后刷新。",
    ),
    "dash.backup.last": ("Última copia {kind}: {when}", "Last backup {kind}: {when}", "Dernière sauvegarde {kind} : {when}", "Letztes Backup {kind}: {when}", "Última cópia {kind}: {when}", "Ultimo backup {kind}: {when}", "前回のコピー {kind}: {when}", "최근 백업 {kind}: {when}", "上次备份 {kind}：{when}"),
    "dash.backup.none": (
        "Todavía no hay copias. La copia completa guarda roles, canales, mensajes e imágenes.",
        "No backups yet. A full backup stores roles, channels, messages and images.",
        "Pas encore de sauvegardes. Une sauvegarde complète garde rôles, salons, messages et images.",
        "Noch keine Backups. Ein Vollbackup speichert Rollen, Kanäle, Nachrichten und Bilder.",
        "Ainda sem cópias. A cópia completa guarda cargos, canais, mensagens e imagens.",
        "Ancora nessun backup. Uno completo salva ruoli, canali, messaggi e immagini.",
        "まだバックアップがありません。完全コピーはロール・チャンネル・メッセージ・画像を保存します。",
        "아직 백업이 없습니다. 전체 백업은 역할, 채널, 메시지, 이미지를 저장합니다.",
        "尚无备份。完整备份会保存身份组、频道、消息与图片。",
    ),
    "dash.announce.edited": ("Edición aplicada: {ok} correctos, {fail} fallidos", "Edit applied: {ok} ok, {fail} failed", "Édition appliquée : {ok} ok, {fail} échecs", "Bearbeitung: {ok} ok, {fail} fehlgeschlagen", "Edição aplicada: {ok} ok, {fail} falhas", "Modifica applicata: {ok} ok, {fail} falliti", "編集適用: 成功 {ok}、失敗 {fail}", "수정 적용: 성공 {ok}, 실패 {fail}", "编辑已应用：成功 {ok}，失败 {fail}"),
    "dash.announce.channel_saved": ("Canal de anuncios guardado", "Announcements channel saved", "Salon d'annonces enregistré", "Ankündigungskanal gespeichert", "Canal de anúncios guardado", "Canale annunci salvato", "お知らせチャンネルを保存", "공지 채널 저장됨", "已保存公告频道"),
    "dash.announce.send_all_title": ("¿Enviar a todos los servidores?", "Send to every server?", "Envoyer à tous les serveurs ?", "An alle Server senden?", "Enviar a todos os servidores?", "Inviare a tutti i server?", "全サーバーに送信しますか？", "모든 서버에 보낼까요?", "发送到所有服务器？"),
    "dash.announce.send_all_text": ("Se publicará en los canales configurados.", "It will post in the configured channels.", "Ça sera publié dans les salons configurés.", "Es wird in den konfigurierten Kanälen gepostet.", "Será publicado nos canais configurados.", "Verrà pubblicato nei canali configurati.", "設定済みチャンネルに投稿されます。", "설정된 채널에 게시됩니다.", "将发布到已配置的频道。"),
    "dash.leave_title": ("¿Sacar a Dabot?", "Remove Dabot?", "Retirer Dabot ?", "Dabot entfernen?", "Remover o Dabot?", "Rimuovere Dabot?", "Dabot を退出させますか？", "Dabot을 내보낼까요?", "移除 Dabot？"),
    "dash.restore_title": ("¿Restaurar estructura?", "Restore structure?", "Restaurer la structure ?", "Struktur wiederherstellen?", "Restaurar estrutura?", "Ripristinare la struttura?", "構造を復元しますか？", "구조를 복원할까요?", "恢复结构？"),
    "dash.restore_text": ("Recrea canales y roles del último backup. Es destructivo.", "Recreates channels and roles from the last backup. Destructive.", "Recrée salons et rôles du dernier backup. Destructif.", "Erstellt Kanäle und Rollen aus dem letzten Backup neu. Destruktiv.", "Recria canais e cargos do último backup. É destrutivo.", "Ricrea canali e ruoli dall'ultimo backup. È distruttivo.", "前回バックアップからチャンネルとロールを再作成。破壊的です。", "최근 백업에서 채널·역할을 다시 만듭니다. 파괴적입니다.", "从最近备份重建频道与身份组。具有破坏性。"),
    "dash.template.apply_title": ("¿Aplicar «{name}»?", "Apply “{name}”?", "Appliquer « {name} » ?", "„{name}“ anwenden?", "Aplicar «{name}»?", "Applicare «{name}»?", "「{name}」を適用しますか？", "«{name}»을(를) 적용할까요?", "应用「{name}」？"),
    "dash.template.apply_text": (
        "Esto BORRA canales y roles actuales y monta logs, verificación, bienvenida, normas y tickets de la plantilla.",
        "This DELETES current channels and roles and builds logs, verification, welcome, rules and tickets from the template.",
        "Ça SUPPRIME salons et rôles actuels et monte logs, vérif, bienvenue, règles et tickets du modèle.",
        "Das LÖSCHT aktuelle Kanäle und Rollen und baut Logs, Verifizierung, Willkommen, Regeln und Tickets aus der Vorlage.",
        "Isto APAGA canais e cargos atuais e monta logs, verificação, boas-vindas, normas e tickets do modelo.",
        "Questo CANCELLA canali e ruoli attuali e monta log, verifica, benvenuto, regole e ticket dal template.",
        "現在のチャンネルとロールを削除し、テンプレートのログ・認証・歓迎・ルール・チケットを構築します。",
        "현재 채널·역할을 지우고 템플릿의 로그, 인증, 환영, 규칙, 티켓을 구성합니다.",
        "这将删除当前频道与身份组，并按模板搭建日志、验证、欢迎、规范与工单。",
    ),
    "dash.nuke_title": ("¿Nukear el servidor?", "Nuke the server?", "Nuke le serveur ?", "Server nuken?", "Nuke o servidor?", "Nuke del server?", "サーバーを nuke しますか？", "서버를 뉴크할까요?", "要 Nuke 服务器吗？"),
    "dash.delete_channel_title": ("¿Borrar canal?", "Delete channel?", "Supprimer le salon ?", "Kanal löschen?", "Apagar canal?", "Eliminare canale?", "チャンネルを削除しますか？", "채널을 삭제할까요?", "删除频道？"),
    "dash.alt_share_on": ("Servidor en la red de alts", "Server on the alt network", "Serveur sur le réseau d'alts", "Server im Alt-Netz", "Servidor na rede de alts", "Server sulla rete alt", "アルト共有ネットワークに参加", "알트 네트워크에 참가", "服务器已加入小号网络"),
    "dash.alt_share_off": ("Servidor fuera de la red", "Server off the network", "Serveur hors du réseau", "Server außerhalb des Netzes", "Servidor fora da rede", "Server fuori dalla rete", "ネットワーク外", "네트워크 밖", "服务器已退出网络"),
    "dash.role_hierarchy_error": ("Error (jerarquía de roles / permisos)", "Error (role hierarchy / permissions)", "Erreur (hiérarchie / permissions)", "Fehler (Rollenhierarchie / Rechte)", "Erro (hierarquia / permissões)", "Errore (gerarchia / permessi)", "エラー（ロール階層 / 権限）", "오류(역할 계층 / 권한)", "错误（身份组层级 / 权限）"),
    "dash.save_perm_error": ("No se pudo guardar (¿permisos del bot?)", "Could not save (bot permissions?)", "Impossible d'enregistrer (permissions bot ?)", "Speichern fehlgeschlagen (Bot-Rechte?)", "Não foi possível guardar (permissões do bot?)", "Impossibile salvare (permessi del bot?)", "保存できませんでした（ボット権限？）", "저장 실패(봇 권한?)", "无法保存（机器人权限？）"),
    "dash.change_fail": ("No se pudo cambiar", "Could not change", "Impossible de changer", "Ändern fehlgeschlagen", "Não foi possível alterar", "Impossibile cambiare", "変更できませんでした", "변경하지 못함", "无法更改"),
    "dash.announce_fail": ("No se pudo enviar el anuncio", "Could not send the announcement", "Impossible d'envoyer l'annonce", "Ankündigung fehlgeschlagen", "Não foi possível enviar o anúncio", "Impossibile inviare l'annuncio", "お知らせを送れませんでした", "공지를 보내지 못함", "无法发送公告"),
    "dash.edit_fail": ("No se pudo editar", "Could not edit", "Impossible d'éditer", "Bearbeiten fehlgeschlagen", "Não foi possível editar", "Impossibile modificare", "編集できませんでした", "수정하지 못함", "无法编辑"),
    "dash.config_load_fail": ("No se pudo cargar la configuración", "Could not load configuration", "Impossible de charger la config", "Konfiguration konnte nicht geladen werden", "Não foi possível carregar a configuração", "Impossibile caricare la configurazione", "設定を読み込めませんでした", "설정을 불러오지 못함", "无法加载配置"),
    "dash.history_load_fail": ("No se pudo cargar el historial", "Could not load history", "Impossible de charger l'historique", "Historie konnte nicht geladen werden", "Não foi possível carregar o histórico", "Impossibile caricare lo storico", "履歴を読み込めませんでした", "기록을 불러오지 못함", "无法加载历史"),
    "dash.announce.recent": ("Enviados recientemente", "Recently sent", "Envoyés récemment", "Kürzlich gesendet", "Enviados recentemente", "Inviati di recente", "最近の送信", "최근 전송", "最近发送"),
    "dash.announce.delivered": ("{sent}/{total} entregados", "{sent}/{total} delivered", "{sent}/{total} livrés", "{sent}/{total} zugestellt", "{sent}/{total} entregues", "{sent}/{total} consegnati", "{sent}/{total} 配信", "{sent}/{total} 전달", "{sent}/{total} 已送达"),
    "dash.control_all": ("Control de todos los servidores", "Control of all servers", "Contrôle de tous les serveurs", "Kontrolle aller Server", "Controlo de todos os servidores", "Controllo di tutti i server", "全サーバーの制御", "모든 서버 제어", "控制全部服务器"),
})


def merge_json():
    for lang_i, lang in enumerate(LANGS):
        path = ROOT / f"{lang}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, vals in NEW.items():
            data[key] = vals[lang_i]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.name} keys={len(data)}")


def js_escape(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace("</", "<\\/")
    )


def rebuild_js():
    js_path = JS
    js = js_path.read_text(encoding="utf-8")
    header_end = js.find("  const STR = {")
    raw_start = js.find("  const RAW_KEYS = {")
    if header_end < 0 or raw_start < 0:
        raise SystemExit("i18n.js markers missing")
    header = js[:header_end]
    tail = js[raw_start:]

    tables = {lang: json.loads((ROOT / f"{lang}.json").read_text(encoding="utf-8")) for lang in LANGS}
    # Keep key order from es
    keys = list(tables["es"].keys())
    parts = ["  const STR = {\n"]
    for lang in LANGS:
        parts.append(f"    {lang}: {{\n")
        for key in keys:
            val = tables[lang].get(key) or tables["en"].get(key) or tables["es"].get(key) or key
            parts.append(f'      "{js_escape(key)}": "{js_escape(val)}",\n')
        parts.append("    },\n")
    parts.append("  };\n\n")
    # Expand RAW_KEYS for new Spanish sources that map to keys
    # Rebuild RAW_KEYS from es values of known keys + keep existing toast maps
    raw_block_end = tail.find("  function translateRaw")
    if raw_block_end < 0:
        raise SystemExit("translateRaw missing")
    # Parse existing RAW_KEYS body to keep toast mappings
    raw_body = tail[:raw_block_end]
    existing = dict(re.findall(r'"((?:\\.|[^"\\])*)"\s*:\s*"((?:\\.|[^"\\])*)"', raw_body))
    # Unescape lightly
    def unesc(s):
        return bytes(s, "utf-8").decode("unicode_escape") if "\\" in s else s

    existing = {unesc(k): unesc(v) for k, v in existing.items()}
    es = tables["es"]
    # Prefer mapping Spanish UI strings to their keys
    for key, val in es.items():
        if isinstance(val, str) and val.strip() and key.startswith(("dash.", "toast.", "nav.", "pr.", "te.", "pm.", "help.", "com.", "vf.", "hero.", "home.", "lv.", "ru.", "ac.")):
            # Don't overwrite toast keys with long paragraphs unnecessarily; still ok
            existing.setdefault(val, key)
    # Force important new Spanish strings
    for key in NEW:
        existing[es[key]] = key

    raw_lines = ["  const RAW_KEYS = {\n"]
    for src, key in sorted(existing.items(), key=lambda kv: kv[0]):
        raw_lines.append(f'    "{js_escape(src)}": "{js_escape(key)}",\n')
    raw_lines.append("  };\n\n")
    new_js = header + "".join(parts) + "".join(raw_lines) + tail[raw_block_end:]
    js_path.write_text(new_js, encoding="utf-8")
    print(f"rebuilt {js_path.name} STR keys={len(keys)} RAW_KEYS={len(existing)}")


if __name__ == "__main__":
    # validate lengths
    for k, v in NEW.items():
        if len(v) != 9:
            raise SystemExit(f"bad arity {k} {len(v)}")
    merge_json()
    rebuild_js()
    print("NEW keys", len(NEW))
