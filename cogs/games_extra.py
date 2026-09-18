"""games_extra.py - Wordle, Hangman, and Battle RPG for DaBot v3"""
import discord
from discord.ext import commands
from discord import app_commands
import random
import logging
import aiohttp

# Session-level cache: {lang: {word: bool}}
_word_cache: dict[str, dict[str, bool]] = {}

# ══════════════════════════════════════════════════════════════════════════════
#  WORD LISTS
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#  ENGLISH WORD LIST  (~1000 common 5-letter words — answers + valid guesses)
# ══════════════════════════════════════════════════════════════════════════════
EN_WORDS = {
    "abbot","abhor","abide","abode","abort","about","above","abyss",
    "acorn","acute","adage","adept","admit","adobe","adopt","adore",
    "adult","after","again","agent","agile","agony","agree","ahead",
    "alarm","album","alert","algae","allay","alley","allot","allow",
    "alloy","aloft","aloud","altar","alter","amaze","amble","amend",
    "angel","anger","angle","angst","anime","annex","annoy","antic",
    "antsy","anvil","aorta","apple","apply","apron","arbor","ardor",
    "arena","argon","armor","aroma","array","arson","arise","asset",
    "atone","attic","audio","audit","augur","avail","avert","avoid",
    "await","awash","awful","awoke","azure","badge","badly","bagel",
    "baggy","baize","baker","balmy","banal","banjo","barge","baron",
    "basil","basin","basis","batch","bathe","batty","bayou","beard",
    "beast","beefy","befit","belle","bench","below","bible","birch",
    "bison","bitty","black","blaze","bleed","blend","blimp","blink",
    "bliss","blitz","bloke","blond","blood","blown","bluff","blunt",
    "blurb","blurt","boast","boggy","bogus","bolts","bonds","bonus",
    "booby","bored","botch","brace","braid","brain","brand","brash",
    "brave","breed","bribe","bride","brief","brink","brisk","broil",
    "broke","broom","brood","broth","brown","brush","bucks","buddy",
    "buggy","bulge","bully","bumpy","bunny","burly","bushy","cabin",
    "cadet","cairn","canal","candy","canon","caper","cargo","carol",
    "caste","catch","catty","cause","caulk","cedar","chafe","chain",
    "chalk","chant","chaos","charm","chase","cheap","check","cheek",
    "cheer","chess","chest","chick","chile","chill","chimp","choir",
    "chore","chose","chunk","cider","civic","civil","clamp","crank",
    "clash","clasp","clean","cleat","cleft","clerk","cling","clips",
    "cloth","cloud","clown","coast","cobra","comet","comic","comma",
    "coral","count","covet","crack","cramp","crane","crank","crawl",
    "crave","crazy","creak","creek","creep","crimp","crisp","croak",
    "crook","crops","cross","crown","cruel","crush","crust","crypt",
    "cubic","curly","curry","cutie","dally","darts","debut","decay",
    "decoy","depot","derby","devil","diced","digit","dingy","dirty",
    "disco","ditty","dizzy","dodge","dogma","dough","dowdy","dowel",
    "dowry","dozer","drain","drank","drape","drawn","dried","drink",
    "drive","drone","drool","drove","drown","duchy","ducky","dully",
    "dumpy","dunce","dusky","dusty","dwarf","dwell","dwelt","dying",
    "eager","early","easel","eaten","edger","eerie","eject","elder",
    "elite","emery","emote","empty","endow","enjoy","envoy","epoch",
    "essay","evade","event","every","exact","exert","exile","exist",
    "expel","extra","exude","fable","facet","faint","false","fancy",
    "farce","fatal","fauna","feast","feign","felon","femur","feral",
    "ferry","field","fiend","fiery","fifty","filth","finch","fishy",
    "fixed","flair","flame","flank","flare","flask","fleet","flesh",
    "flick","flier","fling","flint","flock","flood","flora","flour",
    "flout","flute","foggy","folio","folly","forge","forgo","forte",
    "found","foyer","frame","frank","frond","front","frost","froth",
    "fungi","funky","funny","fuzzy","gaudy","gauze","gavel","gawky",
    "ghost","giddy","given","gleam","glint","gloom","gloss","glyph",
    "goofy","gorge","gouge","grace","grade","grain","grant","grape",
    "grasp","grave","graze","greed","greet","grief","grill","gripe",
    "groan","groin","gruel","gruff","guile","guise","gusto","gypsy",
    "haiku","hairy","handy","happy","harpy","harsh","haste","hasty",
    "hatch","haunt","haven","heady","heard","heart","heave","heavy",
    "hedge","heist","hence","herbs","hippo","holly","honey","honor",
    "horse","hotel","hound","house","human","hyena","icily","image",
    "imply","inane","incur","index","indie","infer","inlet","inner",
    "input","inter","intro","irate","irony","jaunt","jazzy","jiffy",
    "joint","joker","joust","judge","juice","juicy","jumbo","jumpy",
    "kazoo","kebab","kinky","kiosk","kitty","knack","knife","knock",
    "knoll","koala","label","lance","lanky","large","laser","latch",
    "lathe","laugh","layer","leach","leafy","leaky","learn","least",
    "ledge","legal","lemon","lemur","level","levee","light","limbo",
    "liner","lithe","liver","lodge","lofty","logic","lotus","lousy",
    "lover","lucid","lucky","lumpy","lunar","lunch","lymph","lyric",
    "magic","maize","manor","mangy","maple","marry","match","matte",
    "mayor","melee","melon","mercy","merge","messy","metal","micro",
    "might","mimic","minor","minus","mirth","misty","mocha","model",
    "money","month","moody","moral","moron","mossy","motel","motor",
    "mount","mouth","muddy","mulch","mummy","murky","mushy","music",
    "musty","naive","naval","nerdy","nerve","night","ninja","noble",
    "noise","north","notch","novel","nudge","nurse","nymph","occur",
    "ocean","octet","odour","offal","offer","olive","onset","opera",
    "optic","orbit","order","oxide","ozone","paddy","pagan","palsy",
    "panda","panic","pansy","papal","paper","party","paste","pasty",
    "patch","patsy","pause","peace","peach","peaky","pearl","penny",
    "perch","perky","petal","petty","phase","piano","picky","piety",
    "pique","pithy","pixel","pixie","pizza","plain","plaid","plank",
    "plant","plaza","plead","pluck","plumb","plume","plush","poach",
    "podgy","polar","poppy","porch","porky","pouch","pouty","power",
    "prank","prawn","press","price","pride","prime","prism","privy",
    "prize","probe","prone","prose","prove","prune","psalm","pudgy",
    "puffy","pulse","pulpy","punch","punky","pupil","puree","purse",
    "pygmy","queen","quaff","quaky","qualm","query","quest","quick",
    "quiet","quill","quirk","quota","quote","rabbi","radar","radio",
    "radon","raise","rally","ranch","range","rapid","raspy","ratty",
    "raven","reach","react","ready","realm","rebel","regal","reign",
    "relic","renew","repay","repel","repot","rerun","resin","rhyme",
    "rider","rigid","risky","rival","rivet","risen","river","roach",
    "roast","robin","rocky","rogue","roomy","roost","rouge","rough",
    "round","rowdy","ruddy","rugby","ruler","rumba","rumor","rusty",
    "sadly","saint","salad","salty","sandy","sassy","sauce","savor",
    "savvy","scald","scary","scarf","scene","scoff","scold","scone",
    "scope","scout","scrub","seize","sense","serum","setup","seven",
    "sever","shady","shaft","shaky","shale","shall","shame","shape",
    "share","shark","sharp","sheen","sheep","shelf","shell","shift",
    "shine","shirt","shone","short","shout","shrub","shrug","sight",
    "sigma","silky","silly","since","siren","sixth","sixty","skiff",
    "skill","skull","skunk","slain","slant","slash","slate","sleep",
    "sleek","sleet","slept","slide","slime","slope","sloth","slump",
    "smack","small","smart","smash","smell","smile","smite","smoke",
    "smock","snack","snail","snake","sneak","sniff","snore","snort",
    "snowy","soggy","solar","solve","sonic","soppy","sorry","sound",
    "south","space","spade","spank","spare","speak","speed","spell",
    "spicy","spill","spine","spite","spook","spoon","spray","spree",
    "sprig","spunk","squad","squat","squid","stage","stain","stake",
    "stale","stalk","stall","stamp","stand","stare","stark","start",
    "state","steak","steal","stead","steam","steep","steer","stern",
    "stick","stiff","still","stock","stomp","stool","stork","storm",
    "story","stove","strap","straw","stray","strip","strut","study",
    "stuff","stump","style","sugar","sunny","super","surge","surly",
    "swamp","swear","sweat","sweep","sweet","swept","swine","swirl",
    "swoop","sword","syrup","tabby","taboo","taffy","tangy","tardy",
    "tarot","tasty","taunt","tawny","tease","tempo","tense","tepid",
    "terse","thank","thick","thief","thigh","think","thorn","those",
    "three","threw","throw","thumb","thump","tipsy","toast","today",
    "token","tonic","topic","topaz","torch","torso","touch","tough",
    "tower","toxin","trace","train","tramp","trash","triad","trial",
    "trout","trove","truce","truly","trunk","trust","truth","tuber",
    "tulip","tunic","turbo","twice","tweak","twill","twixt","typed",
    "udder","ultra","umbra","uncle","under","unify","union","untie",
    "upper","upset","urban","usher","utter","vague","valid","valor",
    "valve","vapid","vapor","vault","venom","vicar","vigor","vinyl",
    "viola","viral","visor","vista","vivid","vocal","vogue","voter",
    "vouch","wacky","waltz","waste","watch","water","weary","wedge",
    "weird","whale","wheat","wheel","where","which","while","whiff",
    "whirl","whisk","white","whole","wield","windy","witty","world",
    "worry","worse","worst","worth","wrath","wrist","wrong","yacht",
    "yearn","yield","young","yours","zebra","zippy","abhor","askew",
    "ashen","blend","blink","blown","blurt","breed","brier","brisk",
    "broil","burnt","burly","butch","bylaw","cacao","carom","chasm",
    "chive","churn","clack","clamn","clasp","clove","clump","clunk",
    "colon","copse","couch","court","cover","crash","crest","crone",
    "croon","croup","daily","dairy","datum","delta","deter","draft",
    "drawl","drier","drift","drool","depot","epoxy","equip","erect",
    "faker","favor","felon","fifth","first","floss","flunk","freed",
    "fresh","froze","gauge","gilet","gloat","gloss","going","grump",
    "guard","guess","guild","gully","hovel","hunch","idyll","igloo",
    "inept","ingot","jelly","libel","lingo","loafy","macho","maxim",
    "mealy","medic","milky","mince","moldy","mosey","motif","mousy",
    "mulch","nifty","nutty","oaken","onset","outdo","oxide","palmy",
    "pithy","pleat","plume","plunk","privy","ramen","relax","remit",
    "retch","rhino","ripen","sadly","scaly","scamp","scant","scoop",
    "seedy","shiny","skimp","smirk","soapy","speck","spiny","spore",
    "sport","steed","stein","stomp","stoop","strep","sumac","swine",
    "tacky","tamer","teeth","theta","thong","thyme","timid","title",
    "tonal","tenor","tibia","vague","verge","wager","warty","weedy",
    "wiser","woozy","wordy","ombre","onion","overt","quirky","quash",
    "quilt","revue","robot","rover","safer","sinew","skulk","smelt",
    "softy","spate","steed","taint","telly","totem","trump","tryst",
    "twang","twerp","twine","twirl","undue","unfit","vaunt","vouch",
    "vowel","waken","waver","weave","wrung","yodel","yucky","zappy",
    "zonal","abort","breve","buxom","circa","cleft","colic","deter",
    "disco","dowse","elbow","expat","extol","facet","feted","fjord",
    "fluke","froth","gauze","grail","inlay","knave","lathe","lowly",
    "maxim","meant","mogul","navel","nexus","nifty","ninny","nitty",
    "nomad","north","notch","novel","obese","offal","optic","outer",
    "ovoid","pansy","patho","perch","petty","piano","pithy","pivot",
    "plaid","plaza","preen","prude","pudgy","pygmy","qualm","quash",
    "quirk","rabbi","raspy","ratty","repot","rerun","rhino","rivet",
    "robin","rocky","romeo","roomy","rouge","ruddy","rugby","rummy",
    "rupee","rusty","scamp","scant","seedy","seven","showy","sigma",
    "sinew","sixth","skimp","skulk","slain","sleet","smirk","snaky",
    "snowy","softy","spate","squab","steed","stein","stoop","sumac",
    "swine","taint","telly","tempo","tibia","totem","tryst","twang",
    "twerp","twine","undue","unfit","vaunt","verge","wager","waver",
    "wrung","yodel","yucky","zappy","zonal",
}
# Filter: exactly 5 letters, all alpha
EN_WORDS = {w for w in EN_WORDS if len(w) == 5 and w.isalpha()}

# ══════════════════════════════════════════════════════════════════════════════
#  SPANISH WORD LIST  (~1000 common 5-letter words — answers + valid guesses)
# ══════════════════════════════════════════════════════════════════════════════
ES_WORDS = {
    "abajo","abrir","abuso","acero","acoso","adios","adobe","aguas",
    "ahora","ajena","ajeno","aleja","alfil","amino","amigo","ancho",
    "ancla","angel","anima","animo","ansia","antes","apice","apodo",
    "apoya","apuro","aquel","ardid","ardor","arena","armas","armon",
    "astro","asado","ascua","asear","asilo","atado","atras","audio",
    "audaz","autor","avaro","avena","avion","ayuda","babor","baile",
    "bajar","bajio","balde","bambu","banal","banco","barca","baron",
    "basar","batir","beber","bella","bello","besar","bicho","blusa",
    "bolsa","bomba","bordo","bravo","brazo","breve","brisa","bruja",
    "bruto","buceo","buena","bueno","bufon","bulla","burla","busca",
    "buzon","cabal","caida","cajon","calma","calor","calle","calvo",
    "campo","canal","canoa","canto","caoba","capaz","carga","cargo",
    "cariz","carne","carpa","carta","caspa","casar","causa","cavar",
    "cazar","ceder","celda","celos","cenar","censo","cerca","cesto",
    "cetro","chivo","chozo","ciclo","ciego","cielo","cieno","cifra",
    "cinco","citar","clase","clave","clima","cobro","coche","coger",
    "cojin","colmo","colon","comer","comun","conde","conga","coral",
    "corto","cuero","cueva","culpa","curia","cutis","danza","datos",
    "decir","dejar","delta","denso","desde","deseo","deuda","dicho",
    "dieta","dinar","dingo","dique","disco","dolor","donar","donde",
    "dotar","dorso","droga","ducha","dudar","duelo","dunas","duque",
    "ebrio","ejido","elite","elote","enano","enojo","entre","errar",
    "error","espia","etnia","extra","fabla","falda","fallo","falso",
    "fango","farsa","favor","feliz","femur","feria","fiero","ficha",
    "final","finca","firma","fisga","flaco","fobia","fogon","folio",
    "fondo","forja","forma","foton","frase","freno","fresa","fruto",
    "furia","gajan","galan","gamba","garbo","garza","gemir","genio",
    "gente","girar","glosa","golfo","golpe","gordo","gorra","gotas",
    "graba","gramo","grano","grasa","greda","gripe","grito","grupo",
    "gruta","guapo","gueto","guion","guisa","hacer","hasta","hecho",
    "herba","hiato","hiena","hielo","hilos","hogar","honra","honor",
    "horca","horda","hueco","hueso","huida","humor","hurga","hurto",
    "icono","idear","igual","ileso","iluso","impar","impio","indio",
    "irado","jalar","jaleo","jaula","joker","joven","juego","junto",
    "jurar","lagar","largo","lazos","leche","legua","libre","libro",
    "limbo","linea","lince","lista","llano","llena","llave","local",
    "lonja","losas","lugar","luego","lucio","lucha","lunar","magia",
    "magro","madre","malva","mando","manga","mania","manta","marco",
    "marca","marzo","matar","matiz","mayor","macho","media","mejor",
    "menor","menso","metro","miedo","miaja","mirar","mismo","mitad",
    "mocos","molde","monja","monte","morir","moron","morsa","mosca",
    "movil","mugre","multa","mundo","mural","nacer","nadie","nafta",
    "narco","nariz","negro","nicho","nieta","nieve","nivel","noche",
    "noble","norma","norte","nubes","nuevo","nunca","oasis","obras",
    "obrar","obvio","odiar","oeste","oidos","olivo","opaco","optar",
    "orden","osado","oveja","pacer","padre","pagar","pared","pareo",
    "paros","parra","parte","pasar","pasos","patan","patio","parto",
    "pasmo","pausa","pecho","pecio","pedir","pedal","pegar","pelma",
    "penal","penas","perla","perno","perol","perra","pesar","pesca",
    "picar","pieza","pilar","pilon","piojo","pisar","pixel","plaga",
    "plana","plano","plata","playa","plazo","plena","plaza","plomo",
    "pluma","pobre","podar","poder","polar","polca","polla","polvo",
    "pompa","poner","porra","porta","posar","potro","prece","presa",
    "prior","prisa","proel","puedo","pulga","pulso","punto","purga",
    "queso","ragon","rajar","rapaz","rasgo","raspa","ratas","razon",
    "razas","recua","regar","regir","regla","reina","rejas","reino",
    "reloj","remar","renco","retro","raton","reyes","rielo","rinon",
    "ripio","risco","ritmo","robos","roble","rocio","rodar","rodal",
    "rodel","rollo","rombo","rompe","ronda","ropas","rosal","rosco",
    "roque","rozar","rubio","rubor","rugir","ruido","ruina","rumba",
    "rumor","saber","sable","sacar","sacro","sagaz","salir","salon",
    "salmo","salsa","salta","salud","salvo","sanea","saque","sauco",
    "sauce","savia","secar","sedan","segar","segun","selva","senil",
    "senda","sensu","seria","serie","serba","sexto","siega","siete",
    "sigla","siglo","sigma","signo","silva","sioux","sirio","sitio",
    "sobre","sobra","sodio","solar","soler","sonar","sonda","sopas",
    "soplo","sorbo","sordo","sorgo","sotol","suave","subir","sudor",
    "sueco","suelo","sumar","susto","sutil","surco","tabla","tajin",
    "talco","talon","talud","tamiz","tango","tapar","tapir","tapiz",
    "tarot","tarro","tasar","tasca","tarde","tedio","tejon","temas",
    "temor","tener","tenia","terco","termo","testa","tigra","tigre",
    "timba","timbo","titan","tobas","tocar","todos","toldo","tonga",
    "topia","topil","topar","tordo","toril","torno","torpe","torso",
    "toser","tosco","total","traer","traba","trago","trapo","traza",
    "trazo","triga","troje","tropa","trote","trozo","truca","trufa",
    "tubos","turba","turco","turno","tuteo","tutor","ujier","ultra",
    "umbra","unico","union","usado","usual","vacua","vagar","vagon",
    "vaina","valer","valor","vapor","varal","vareo","varon","vasto",
    "vatio","vecin","vedij","vedar","velar","vello","venda","venir",
    "venus","verde","veraz","verbo","verja","verso","viaje","vicio",
    "viene","viejo","vigor","viril","virus","visor","vista","vivaz",
    "volar","vomit","voraz","votar","vuelo","yacer","yegua","yerro",
    "yermo","zanco","zanja","zarpa",
    # Extra words to reach ~1000
    "acebo","acido","acune","adula","agave","alcol","aldea","alero",
    "algas","algod","algon","algun","alijo","aliso","altoz","amada",
    "ambar","amena","amigo","amiga","ampli","ancas","angus","apice",
    "arbol","arder","arete","argot","arnes","arras","arque","artes",
    "astas","asuma","atajo","ataud","atriz","atufo","azucar","azule",
    "bache","bahia","balon","banda","barco","barba","batid","bayar",
    "beato","bocon","bocio","bodas","boina","bollo","boton","broma",
    "bruja","brujo","buzon","cabal","cacau","cacao","cadiz","cafre",
    "caima","calce","campe","capul","casar","casta","caton","cebra",
    "ceibo","cejas","celos","celta","censo","ceras","cerco","chaco",
    "cimas","circo","cisco","clavo","cobij","cofia","coima","colon",
    "comal","coral","coran","corza","cosco","coser","crudo","cuajo",
    "cubia","cuero","curan","cursi","dance","dardo","decor","delco",
    "demas","denso","dense","dogma","donna","dueto","dulce","efebo",
    "efigie","embar","empuj","enano","enfer","enlac","equip","escap",
    "escom","espik","estab","fabio","falsa","falco","fajin","feroz",
    "fibra","flema","flora","flujo","focos","folga","franc","frago",
    "freno","fumig","fusil","galop","gasto","gazap","gleba","golfa",
    "gonzo","gozon","grajo","gueis","gueto","guiso","hampa","harpa",
    "hayar","hipic","hipno","hobos","hocic","homid","honda","human",
    "icona","ideal","idiom","imago","incol","induc","inert","infam",
    "jabon","japon","jazal","jirón","jugon","jurel","lecón","legat",
    "limon","llaga","lloro","local","lomba","longe","lorco","lusco",
    "macao","macra","mambo","manco","meral","mesón","milia","mohín",
    "moloc","momia","monje","moqui","morra","motin","motil","muchi",
    "musgo","nabor","narco","niñez","noria","noctu","nomad","omega",
    "onzas","orbes","orcas","orfeo","orgaz","paila","palco","panza",
    "papal","parda","parla","patin","pavon","payar","peche","pelot",
    "penia","pilaf","pilón","pizza","pobla","pocas","polvo","pompo",
    "proel","prueb","pujar","punal","rabic","raleo","rapal","rapil",
    "recua","reojo","resma","retal","rezar","riata","ricor","rinon",
    "risco","rivna","ronza","rosma","rotla","runco","sabor","sacas",
    "sacre","salaz","salca","senor","sensu","senzo","sigma","sisto",
    "sizar","sobra","soler","solfa","solla","solom","somna","sumis",
    "tacho","tapas","techo","telón","tempo","tenta","tepuy","terca",
    "tesón","tisco","tocho","totem","trata","tripa","trocha","truqu",
    "tubor","tunda","tunia","tuteo","ujier","ulula","vanal","velon",
    "veros","vidro","vigas","visco","vuesa","yugo","zorra","zurra",
}
ES_WORDS = {w for w in ES_WORDS if len(w) == 5 and w.isalpha()}

# ── HANGMAN WORDS ─────────────────────────────────────────────────────────────
HANGMAN_WORDS = {
    "en": [
        # Technology & Science
        "python","discord","programming","keyboard","monitor","server",
        "database","algorithm","function","variable","internet","computer",
        "javascript","telescope","microscope","helicopter","satellite","radiation",
        "electricity","chemistry","atmosphere","laboratory","hypothesis","experiment",
        "chromosome","ecosystem","photosynthesis","evaporation","metamorphosis",
        "infrastructure","cryptocurrency","artificial","intelligence","algorithm",
        "blockchain","cybersecurity","nanotechnology","biotechnology","robotics",
        "astronomy","anthropology","archaeology","psychology","philosophy",
        # Animals & Nature
        "dragon","wizard","elephant","giraffe","penguin","hedgehog","crocodile",
        "rhinoceros","butterfly","dolphin","chimpanzee","flamingo","kangaroo",
        "chameleon","platypus","octopus","wolverine","salamander","porcupine",
        "armadillo","capybara","narwhal","axolotl","jaguar","panther","cheetah",
        "mongoose","meerkat","wombat","lemur","toucan","macaw","pelican",
        "albatross","hammerhead","barracuda","piranha","komodo","tarantula",
        "scorpion","centipede","millipede","dragonfly","praying","mantis",
        # Geography & Places
        "volcano","tsunami","avalanche","hurricane","earthquake","continent",
        "peninsula","archipelago","savanna","rainforest","tundra","plateau",
        "glacier","waterfall","canyon","fjord","lagoon","mangrove","tributary",
        "equator","hemisphere","meridian","latitude","longitude","altitude",
        "mediterranean","himalayas","sahara","amazon","antarctica","patagonia",
        "caribbean","scandinavia","mesopotamia","polynesia","micronesia",
        # History & Culture
        "revolution","civilization","renaissance","reformation","inquisition",
        "crusade","pharaoh","gladiator","colosseum","pantheon","parthenon",
        "acropolis","labyrinth","mythology","odyssey","shakespeare","napoleon",
        "cathedral","monastery","fortress","citadel","mausoleum","pyramid",
        "hieroglyph","cuneiform","manuscript","parchment","alchemy","astrology",
        # Food & Drink
        "cappuccino","croissant","espresso","barbecue","guacamole","quesadilla",
        "enchilada","marmalade","lemonade","cinnamon","cardamom","turmeric",
        "asparagus","artichoke","avocado","cauliflower","broccoli","eggplant",
        "pomegranate","persimmon","passionfruit","starfruit","jackfruit",
        # Sports & Entertainment
        "skateboard","tournament","championship","basketball","volleyball",
        "badminton","quarterback","lacrosse","bobsled","decathlon","pentathlon",
        "marathon","synchronize","gymnastics","trampoline","archery","fencing",
        "parachute","rollercoaster","acrobatics","choreography","orchestra",
        "symphony","concerto","overture","kaleidoscope","hologram","animation",
        # Words (long & challenging)
        "embarrassment","phenomenon","bureaucracy","Mediterranean","perseverance",
        "hallucination","philosophical","extraordinary","constellation","encyclopedia",
        "photosynthesis","thunderstorm","camouflage","magnificent","celebration",
        "metamorphosis","kaleidoscope","catastrophe","serendipity","melancholy",
        "ambiguous","clandestine","eloquence","flamboyant","gregarious",
        "idiosyncratic","juxtaposition","labyrinthine","meticulous","nonchalant",
        "ostentatious","paradoxical","quintessential","rhapsody","sophisticated",
        "transcendent","ubiquitous","vicarious","whimsical","xenophobia","zealous",
    ],
    "es": [
        # Tecnología & Ciencia
        "programacion","computadora","teclado","pantalla","servidor","javascript",
        "algoritmo","inteligencia","tecnologia","telecomunicaciones","satelite",
        "electricidad","quimica","atmosfera","laboratorio","hipotesis","experimento",
        "cromosoma","ecosistema","fotosintesis","evaporacion","metamorfosis",
        "infraestructura","criptomoneda","nanotecnologia","biotecnologia","robotica",
        "astronomia","antropologia","arqueologia","psicologia","filosofia",
        # Animales & Naturaleza
        "dinosaurio","mariposa","elefante","jirafa","cocodrilo","rinoceronte",
        "delfin","chimpance","flamenco","canguro","camaleon","ornitorrinco",
        "pulpo","capibara","caballo","aguila","serpiente","escarabajo",
        "langosta","medusa","tortuga","avestruz","murmullo","pelicano",
        "albatros","barracuda","piraña","tarantula","escorpion","cienp",
        "libelula","mantis","abejorro","mariposa","luciernaga","cucaracha",
        # Geografia & Lugares
        "volcan","tsunami","avalancha","huracan","terremoto","continente",
        "peninsula","archipielago","sabana","selva","tundra","meseta",
        "glaciar","cascada","canon","laguna","manglar","afluente",
        "ecuador","hemisferio","meridiano","latitud","longitud","altitud",
        "mediterraneo","himalaya","sahara","amazonia","antartida","patagonia",
        "caribe","escandinavia","mesopotamia","polinesia","micronesia",
        # Historia & Cultura
        "revolucion","civilizacion","renacimiento","reformacion","inquisicion",
        "cruzada","faraon","gladiador","coliseo","panteon","partenon",
        "acropolis","laberinto","mitologia","odisea","shakespeare","napoleon",
        "catedral","monasterio","fortaleza","ciudadela","mausoleo","piramide",
        "jeroglifico","cuneiforme","manuscrito","pergamino","alquimia","astrologia",
        "conquistador","colonizacion","independencia","constitucion","federalismo",
        # Comida & Bebida
        "capuchino","croissant","espresso","barbacoa","guacamole","quesadilla",
        "enchilada","mermelada","limonada","canela","cardamomo","curcuma",
        "esparrago","alcachofa","aguacate","coliflor","brocoli","berenjena",
        "granada","caqui","maracuya","carambola","jacafruit","mangostan",
        "gazpacho","paella","ceviche","empanada","churros","tamale","pozole",
        # Deportes & Entretenimiento
        "skateboard","torneo","campeonato","baloncesto","voleibol",
        "badminton","lacrosse","descenso","decatlon","pentatlon",
        "maraton","sincronizacion","gimnasia","trampolín","arqueria","esgrima",
        "paracaidas","montaniarussa","acrobacias","coreografia","orquesta",
        "sinfonia","concierto","obertura","caleidoscopio","holograma","animacion",
        # Palabras largas y complejas
        "extraordinario","fenomeno","burocracia","perseverancia","alucinacion",
        "filosofico","constelacion","enciclopedia","fotosintesis","tormenta",
        "camuflaje","magnifico","celebracion","metamorfosis","catastrofe",
        "serendipia","melancolia","ambiguo","clandestino","elocuencia",
        "extravagante","gregoriano","idiosincratico","yuxtaposicion","meticuloso",
        "ostentoso","paradojico","quintaesencia","rapsodia","sofisticado",
        "trascendente","ubicuo","vicario","caprichoso","globalizacion",
        "biodiversidad","supernova","agujero","asteroide","meteorito",
        "biblioteca","academia","fantasma","leyenda","guerreros","vikingos",
        "faro","constelacion","arquitectura","helicoptero","criptomoneda",
    ],
}

HANGMAN_STAGES = [
    "```\n  +---+\n  |   |\n      |\n      |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n      |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n  |   |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n /|   |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n /|\\  |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n /|\\  |\n /    |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n      |\n=========```",
]


# ══════════════════════════════════════════════════════════════════════════════
#  WORDLE
# ══════════════════════════════════════════════════════════════════════════════

WORDLE_LANG_DATA = {
    "en": {"words": EN_WORDS, "label": "English", "api_lang": "en"},
    "es": {"words": ES_WORDS, "label": "Spanish", "api_lang": "es"},
}


class WordleGame:
    def __init__(self, word: str, player: discord.Member, lang: str):
        self.word = word.lower()
        self.player = player
        self.lang = lang
        self.guesses: list[str] = []
        self.max_guesses = 6

    @property
    def won(self): return bool(self.guesses) and self.guesses[-1] == self.word
    @property
    def lost(self): return len(self.guesses) >= self.max_guesses and not self.won
    @property
    def over(self): return self.won or self.lost

    def is_valid_local(self, word: str) -> bool:
        """Fast check: is this word in our local set?"""
        return word.lower() in WORDLE_LANG_DATA[self.lang]["words"]

    async def is_valid_word(self, word: str, session: aiohttp.ClientSession) -> bool:
        """Full check: embedded list first, then Free Dictionary API."""
        word = word.lower()
        # 1. Fast path — embedded list
        if self.is_valid_local(word):
            return True
        # 2. Cache lookup
        cache = _word_cache.setdefault(self.lang, {})
        if word in cache:
            return cache[word]
        # 3. Free Dictionary API
        api_lang = WORDLE_LANG_DATA[self.lang]["api_lang"]
        url = f"https://api.dictionaryapi.dev/api/v2/entries/{api_lang}/{word}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2.5)) as resp:
                valid = resp.status == 200
        except Exception:
            valid = True  # Fail open: if API is down, accept the word
        cache[word] = valid
        return valid

    def make_guess(self, guess: str) -> str:
        guess = guess.lower()
        self.guesses.append(guess)
        return self._build_row(guess)

    def _build_row(self, guess: str) -> str:
        result = [None] * 5
        word_chars = list(self.word)
        # Pass 1 — correct position
        for i, (g, w) in enumerate(zip(guess, word_chars)):
            if g == w:
                result[i] = "🟩"
                word_chars[i] = None
        # Pass 2 — wrong position
        for i, g in enumerate(guess):
            if result[i]: continue
            if g in word_chars:
                result[i] = "🟨"
                word_chars[word_chars.index(g)] = None
            else:
                result[i] = "⬛"
        return "".join(result) + "  " + " ".join(f"`{c.upper()}`" for c in guess)

    def build_board(self) -> str:
        rows = [self._build_row(g) for g in self.guesses]
        rows += ["⬜⬜⬜⬜⬜"] * (self.max_guesses - len(self.guesses))
        return "\n".join(rows)


def build_wordle_embed(game: WordleGame, status: str) -> discord.Embed:
    lang_label = WORDLE_LANG_DATA[game.lang]["label"]
    embed = discord.Embed(
        title=f"🟩 Wordle — {lang_label}",
        description=game.build_board(),
        color=discord.Color.green() if game.won else discord.Color.blurple()
    )
    embed.add_field(name="Status", value=status, inline=False)
    embed.set_footer(text=f"Player: {game.player.display_name} • {len(game.guesses)}/6 guesses")
    return embed


class WordleModal(discord.ui.Modal, title="Enter your guess"):
    guess = discord.ui.TextInput(label="5-letter word", min_length=5, max_length=5, placeholder="e.g. CRANE / MUNDO")

    def __init__(self, game: WordleGame, view: "WordleView", session: aiohttp.ClientSession):
        super().__init__()
        self.game = game
        self.parent_view = view
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        word = self.guess.value.lower().strip()
        if not word.isalpha() or len(word) != 5:
            await interaction.response.send_message("❌ Must be exactly 5 letters.", ephemeral=True)
            return

        # Fast path: word is in embedded list — no API call needed
        if self.game.is_valid_local(word):
            valid = True
            need_api = False
        else:
            need_api = True
            valid = False

        if need_api:
            # Defer to allow time for the API call (usually <300ms)
            await interaction.response.defer()
            valid = await self.game.is_valid_word(word, self.session)
            if not valid:
                await interaction.followup.send(
                    f"❌ **{word.upper()}** is not a recognized word. Try again!", ephemeral=True
                )
                return
            # Process guess and update the game message directly
            self.game.make_guess(word)
            if self.game.won:
                self.parent_view.stop()
                for item in self.parent_view.children: item.disabled = True
                msg = f"🎉 **{interaction.user.display_name}** guessed it in **{len(self.game.guesses)}/6!** The word was **{self.game.word.upper()}**."
            elif self.game.lost:
                self.parent_view.stop()
                for item in self.parent_view.children: item.disabled = True
                msg = f"😔 Game over! The word was **{self.game.word.upper()}**."
            else:
                msg = f"Guess **{len(self.game.guesses)}/6** — keep going!"
            # Use edit_original_response since we deferred
            await interaction.edit_original_response(
                embed=build_wordle_embed(self.game, msg), view=self.parent_view
            )
            return

        # Word was valid locally — respond instantly
        self.game.make_guess(word)
        if self.game.won:
            self.parent_view.stop()
            for item in self.parent_view.children: item.disabled = True
            msg = f"🎉 **{interaction.user.display_name}** guessed it in **{len(self.game.guesses)}/6!** The word was **{self.game.word.upper()}**."
        elif self.game.lost:
            self.parent_view.stop()
            for item in self.parent_view.children: item.disabled = True
            msg = f"😔 Game over! The word was **{self.game.word.upper()}**."
        else:
            msg = f"Guess **{len(self.game.guesses)}/6** — keep going!"
        await interaction.response.edit_message(embed=build_wordle_embed(self.game, msg), view=self.parent_view)


class WordleView(discord.ui.View):
    def __init__(self, game: WordleGame, session: aiohttp.ClientSession):
        super().__init__(timeout=300)
        self.game = game
        self.session = session

    @discord.ui.button(label="Guess a word", style=discord.ButtonStyle.primary, emoji="💬")
    async def guess_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.player:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return
        await interaction.response.send_modal(WordleModal(self.game, self, self.session))

    @discord.ui.button(label="Give up", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def give_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.player:
            await interaction.response.send_message("❌ Not your game!", ephemeral=True)
            return
        self.stop()
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(
            embed=build_wordle_embed(self.game, f"😔 You gave up! The word was **{self.game.word.upper()}**."),
            view=self
        )


# ══════════════════════════════════════════════════════════════════════════════
#  HANGMAN
# ══════════════════════════════════════════════════════════════════════════════

class HangmanGame:
    def __init__(self, word: str, player: discord.Member, lang: str):
        self.word = word.lower()
        self.player = player
        self.lang = lang
        self.guessed: set[str] = set()
        self.wrong: list[str] = []
        self.max_wrong = 6

    @property
    def display_word(self):
        return " ".join(c if c in self.guessed else "\\_" for c in self.word)
    @property
    def won(self): return all(c in self.guessed for c in self.word)
    @property
    def lost(self): return len(self.wrong) >= self.max_wrong
    @property
    def over(self): return self.won or self.lost

    def guess_letter(self, letter: str) -> str:
        letter = letter.lower()
        if letter in self.guessed or letter in self.wrong:
            return "already"
        self.guessed.add(letter)
        if letter not in self.word:
            self.wrong.append(letter)
            return "wrong"
        return "correct"


def build_hangman_embed(game: HangmanGame, extra: str = "") -> discord.Embed:
    lang_label = "English" if game.lang == "en" else "Español"
    stage = HANGMAN_STAGES[min(len(game.wrong), 6)]
    color = discord.Color.green() if game.won else (discord.Color.red() if game.lost else discord.Color.orange())
    embed = discord.Embed(title=f"💀 Hangman — {lang_label}", color=color)
    embed.add_field(name="Progress", value=stage, inline=False)
    embed.add_field(name="Word", value=f"`{game.display_word}`", inline=False)
    if game.wrong:
        embed.add_field(name="Wrong guesses", value=" ".join(f"`{c.upper()}`" for c in game.wrong), inline=True)
    embed.add_field(name="Lives", value="❤️" * (game.max_wrong - len(game.wrong)) + "🖤" * len(game.wrong), inline=True)
    if extra:
        embed.add_field(name="Last", value=extra, inline=False)
    embed.set_footer(text=f"Player: {game.player.display_name}")
    return embed


class HangmanModal(discord.ui.Modal, title="Guess a letter"):
    letter = discord.ui.TextInput(label="Letter", min_length=1, max_length=1)

    def __init__(self, game: HangmanGame, view: "HangmanView"):
        super().__init__()
        self.game = game
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction):
        letter = self.letter.value.lower()
        if not letter.isalpha():
            await interaction.response.send_message("❌ Enter a single letter.", ephemeral=True)
            return
        result = self.game.guess_letter(letter)
        feedback = {
            "already": f"⚠️ Already guessed `{letter.upper()}`!",
            "wrong": f"❌ `{letter.upper()}` is not in the word.",
            "correct": f"✅ `{letter.upper()}` is correct!",
        }[result]

        view = self.parent_view
        if self.game.won or self.game.lost:
            view.stop()
            for item in view.children: item.disabled = True

        embed = build_hangman_embed(self.game, feedback)
        if self.game.won:
            embed.add_field(name="🎉 You won!", value=f"The word was **{self.game.word.upper()}**.", inline=False)
        elif self.game.lost:
            embed.add_field(name="💀 Game over!", value=f"The word was **{self.game.word.upper()}**.", inline=False)

        await interaction.response.edit_message(embed=embed, view=view)


class HangmanView(discord.ui.View):
    def __init__(self, game: HangmanGame):
        super().__init__(timeout=300)
        self.game = game

    @discord.ui.button(label="Guess a letter", style=discord.ButtonStyle.primary, emoji="🔤")
    async def guess_letter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.player:
            await interaction.response.send_message("❌ Not your game!", ephemeral=True)
            return
        await interaction.response.send_modal(HangmanModal(self.game, self))

    @discord.ui.button(label="Give up", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def give_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.player:
            await interaction.response.send_message("❌ Not your game!", ephemeral=True)
            return
        self.stop()
        for item in self.children: item.disabled = True
        embed = build_hangman_embed(self.game)
        embed.add_field(name="Result", value=f"😔 Gave up! Word was **{self.game.word.upper()}**.", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)


# ══════════════════════════════════════════════════════════════════════════════
#  BATTLE RPG
# ══════════════════════════════════════════════════════════════════════════════

class BattleState:
    def __init__(self, p1, p2, p1_level, p2_level):
        self.players = [p1, p2]
        # Cap level influence so high-level users cannot stomp new members.
        e1 = max(1, min(int(p1_level or 1), 12))
        e2 = max(1, min(int(p2_level or 1), 12))
        self.levels = [int(p1_level or 1), int(p2_level or 1)]
        self.eff = [e1, e2]
        self.hp = [100 + e1 * 6, 100 + e2 * 6]
        self.max_hp = self.hp[:]
        self.atk = [14 + e1, 14 + e2]
        self.heals_left = [2, 2]
        self.special_left = [1, 1]
        self.guard = [False, False]
        self.turn = 0
        self.log = []

    @property
    def current(self): return self.players[self.turn]
    @property
    def opp(self): return 1 - self.turn

    def _apply_damage(self, raw):
        target = self.opp
        if self.guard[target]:
            raw = max(1, raw // 2)
            self.guard[target] = False
            blocked = True
        else:
            blocked = False
        self.hp[target] = max(0, self.hp[target] - raw)
        return raw, blocked

    def attack(self):
        import random as _r
        dmg = _r.randint(int(self.atk[self.turn] * 0.75), int(self.atk[self.turn] * 1.15))
        crit = _r.random() < 0.12
        if crit:
            dmg = int(dmg * 1.4)
        dealt, blocked = self._apply_damage(dmg)
        msg = f"⚔️ **{self.current.display_name}** golpea por **{dealt}**"
        if crit:
            msg += " ✨ CRIT"
        if blocked:
            msg += " (bloqueado a la mitad)"
        msg += "!"
        self.turn = self.opp
        return msg

    def special(self):
        if self.special_left[self.turn] <= 0:
            return "❌ Sin especial restante. Elige otra acción."
        import random as _r
        self.special_left[self.turn] -= 1
        dmg = int(self.atk[self.turn] * 1.7) + _r.randint(0, 6)
        dealt, blocked = self._apply_damage(dmg)
        msg = f"🦞 **{self.current.display_name}** usa **Pinza de langosta** por **{dealt}**"
        if blocked:
            msg += " (bloqueado)"
        msg += "!"
        self.turn = self.opp
        return msg

    def defend(self):
        self.guard[self.turn] = True
        msg = f"🛡️ **{self.current.display_name}** se cubre. El próximo golpe se reduce a la mitad."
        self.turn = self.opp
        return msg

    def heal(self):
        import random as _r
        if self.heals_left[self.turn] <= 0:
            return "❌ Sin curas restantes."
        self.heals_left[self.turn] -= 1
        restore = _r.randint(12, 22)
        self.hp[self.turn] = min(self.max_hp[self.turn], self.hp[self.turn] + restore)
        msg = f"💚 **{self.current.display_name}** cura **{restore}** HP ({self.heals_left[self.turn]} curas left)."
        self.turn = self.opp
        return msg

    @property
    def winner(self):
        if self.hp[0] <= 0: return self.players[1]
        if self.hp[1] <= 0: return self.players[0]
        return None


def build_battle_embed(state: BattleState, last: str = "") -> discord.Embed:
    def bar(hp, mx):
        f = int((hp / mx) * 10)
        return "█" * f + "░" * (10 - f) + f" **{hp}/{mx}**"
    embed = discord.Embed(title="⚔️ Battle RPG", color=discord.Color.gold() if state.winner else discord.Color.from_str("#E23D28"))
    for i in range(2):
        crown = "👑 " if state.turn == i and not state.winner else ""
        extra = f"Lv {state.levels[i]} · atk {state.atk[i]} · curas {state.heals_left[i]} · especial {state.special_left[i]}"
        embed.add_field(
            name=f"{crown}{state.players[i].display_name}",
            value=f"{bar(state.hp[i], state.max_hp[i])}\n{extra}",
            inline=False,
        )
    if last: embed.add_field(name="Última acción", value=last, inline=False)
    if state.winner: embed.add_field(name="🏆 Winner!", value=state.winner.mention, inline=False)
    else: embed.set_footer(text=f"Turno de {state.current.display_name} · el nivel está limitado para equilibrar")
    return embed


class BattleView(discord.ui.View):
    def __init__(self, state: BattleState):
        super().__init__(timeout=300)
        self.state = state

    @discord.ui.button(label="⚔️ Attack", style=discord.ButtonStyle.danger)
    async def attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.state.current:
            await interaction.response.send_message("⏳ Wait for your turn!", ephemeral=True)
            return
        msg = self.state.attack()
        if self.state.winner:
            self.stop()
            for item in self.children: item.disabled = True
        await interaction.response.edit_message(embed=build_battle_embed(self.state, msg), view=self)

    @discord.ui.button(label="💚 Heal", style=discord.ButtonStyle.success)
    async def heal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.state.current:
            await interaction.response.send_message("⏳ Wait for your turn!", ephemeral=True)
            return
        msg = self.state.heal()
        if msg.startswith("❌"):
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.edit_message(embed=build_battle_embed(self.state, msg), view=self)

    @discord.ui.button(label="🛡️ Guard", style=discord.ButtonStyle.secondary)
    async def guard_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.state.current:
            await interaction.response.send_message("⏳ Wait for your turn!", ephemeral=True)
            return
        msg = self.state.defend()
        await interaction.response.edit_message(embed=build_battle_embed(self.state, msg), view=self)

    @discord.ui.button(label="🦞 Special", style=discord.ButtonStyle.primary)
    async def special_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.state.current:
            await interaction.response.send_message("⏳ Wait for your turn!", ephemeral=True)
            return
        msg = self.state.special()
        if msg.startswith("❌"):
            await interaction.response.send_message(msg, ephemeral=True)
            return
        if self.state.winner:
            self.stop()
            for item in self.children:
                item.disabled = True
        await interaction.response.edit_message(embed=build_battle_embed(self.state, msg), view=self)


# ══════════════════════════════════════════════════════════════════════════════
#  COG
# ══════════════════════════════════════════════════════════════════════════════

class GamesExtra(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("Dabot")

    minigame = app_commands.Group(name="minigame", description="🎮 Play extra minigames!")

    async def pick_wordle_word(self, lang: str) -> str:
        """Returns an answer word. 2% chance of pulling from random-word API (EN only)."""
        words = list(WORDLE_LANG_DATA[lang]["words"])
        # Only try the random word API for English (no good free Spanish API)
        if lang == "en" and random.random() < 0.02:
            try:
                url = "https://random-word-api.herokuapp.com/word?length=5"
                async with self.bot.session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, list):
                            candidate = data[0].lower().strip()
                            if len(candidate) == 5 and candidate.isalpha():
                                return candidate
            except Exception:
                pass  # Fall through to local list if API fails
        return random.choice(words)

    @minigame.command(name="wordle", description="Play Wordle — guess the 5-letter word in 6 tries!")
    @app_commands.describe(language="Choose the language for the puzzle")
    @app_commands.choices(language=[
        app_commands.Choice(name="English 🇬🇧", value="en"),
        app_commands.Choice(name="Español 🇪🇸", value="es"),
    ])
    async def minigame_wordle(self, interaction: discord.Interaction, language: str):
        await interaction.response.defer()
        data = WORDLE_LANG_DATA[language]
        word = await self.pick_wordle_word(language)
        game = WordleGame(word, interaction.user, language)
        view = WordleView(game, self.bot.session)
        await interaction.followup.send(
            embed=build_wordle_embed(game, f"Click **Guess a word** to start! ({data['label']})"),
            view=view
        )

    @minigame.command(name="hangman", description="Play Hangman — guess the hidden word letter by letter!")
    @app_commands.describe(language="Choose the language for the puzzle")
    @app_commands.choices(language=[
        app_commands.Choice(name="English 🇬🇧", value="en"),
        app_commands.Choice(name="Español 🇪🇸", value="es"),
    ])
    async def minigame_hangman(self, interaction: discord.Interaction, language: str):
        await interaction.response.defer()
        word = random.choice(HANGMAN_WORDS[language])
        game = HangmanGame(word, interaction.user, language)
        view = HangmanView(game)
        await interaction.followup.send(embed=build_hangman_embed(game), view=view)

    @minigame.command(name="battle", description="Challenge another member to an RPG battle!")
    @app_commands.describe(opponent="The member you want to battle")
    async def minigame_battle(self, interaction: discord.Interaction, opponent: discord.Member):
        if opponent.bot or opponent == interaction.user:
            await interaction.response.send_message("❌ You need to challenge a real human!", ephemeral=True)
            return

        await interaction.response.defer()
        p1 = await self.bot.db.fetch("SELECT level FROM guild_levels WHERE guild_id = ? AND user_id = ?", interaction.guild.id, interaction.user.id)
        p2 = await self.bot.db.fetch("SELECT level FROM guild_levels WHERE guild_id = ? AND user_id = ?", interaction.guild.id, opponent.id)
        p1_level = p1[0] if p1 else 1
        p2_level = p2[0] if p2 else 1

        embed = discord.Embed(
            title="⚔️ Battle Challenge!",
            description=f"{interaction.user.mention} challenges {opponent.mention}!\n\n**{interaction.user.display_name}** — Level {p1_level}\n**{opponent.display_name}** — Level {p2_level}",
            color=discord.Color.orange()
        )
        accept_view = discord.ui.View(timeout=60)

        async def accept(btn: discord.Interaction):
            if btn.user != opponent:
                await btn.response.send_message("❌ Only the challenged player can accept.", ephemeral=True)
                return
            accept_view.stop()
            state = BattleState(interaction.user, opponent, p1_level, p2_level)
            await btn.response.edit_message(embed=build_battle_embed(state), view=BattleView(state))

        async def decline(btn: discord.Interaction):
            if btn.user != opponent:
                await btn.response.send_message("❌ Only the challenged player can decline.", ephemeral=True)
                return
            accept_view.stop()
            await btn.response.edit_message(content=f"❌ {opponent.display_name} declined.", embed=None, view=None)

        a = discord.ui.Button(label="⚔️ Accept", style=discord.ButtonStyle.success)
        d = discord.ui.Button(label="❌ Decline", style=discord.ButtonStyle.danger)
        a.callback = accept
        d.callback = decline
        accept_view.add_item(a)
        accept_view.add_item(d)
        await interaction.followup.send(content=opponent.mention, embed=embed, view=accept_view)


async def setup(bot):
    await bot.add_cog(GamesExtra(bot))
