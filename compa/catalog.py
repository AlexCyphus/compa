"""Languages Compa can add as a profile, with defaults that were checked to work (voice + Whisper round trip)."""
import json
from dataclasses import dataclass

from compa.settings import REPO, profile_names

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


@dataclass(frozen=True)
class CatalogLanguage:
    key: str
    name: str
    flag: str
    code: str
    variety: str
    voice: str
    news_from: str
    fillers: str


CATALOG = [
    CatalogLanguage("spanish", "Spanish", "🇪🇸", "es", "Colombian Spanish", "kokoro:ef_dora", "Colombia and Latin America",
                    "Eh, pues... o sea, este, bueno, es que, eh, no sé."),
    CatalogLanguage("french", "French", "🇫🇷", "fr", "Metropolitan French", "kokoro:ff_siwis", "France",
                    "Euh... ben... alors, je sais pas, euh."),
    CatalogLanguage("german", "German", "🇩🇪", "de", "North German (Hochdeutsch)", "Anna", "Germany, Austria and Switzerland",
                    "Äh, also... naja, ich meine, hm, keine Ahnung."),
    CatalogLanguage("italian", "Italian", "🇮🇹", "it", "Standard Italian", "kokoro:if_sara", "Italy",
                    "Ehm, cioè... allora, insomma, boh, non so."),
    CatalogLanguage("portuguese", "Portuguese", "🇧🇷", "pt", "Brazilian Portuguese", "kokoro:pf_dora", "Brazil",
                    "É, tipo... então, sabe, né, sei lá."),
    CatalogLanguage("english", "English", "🇺🇸", "en", "American English", "kokoro:af_heart", "the United States",
                    "Uh, well... like, you know, I mean, um."),
    CatalogLanguage("catalan", "Catalan", "🇦🇩", "ca", "Central Catalan (Barcelona)", "Montse", "Catalonia",
                    "Eh... doncs, o sigui, bé, és que, eh, no ho sé."),
    CatalogLanguage("dutch", "Dutch", "🇳🇱", "nl", "Netherlands Dutch", "Xander", "the Netherlands and Belgium",
                    "Eh, nou... dus, weet je, ehm, geen idee."),
    CatalogLanguage("polish", "Polish", "🇵🇱", "pl", "Standard Polish", "Zosia", "Poland",
                    "Yyy, no... wiesz, znaczy, eee, nie wiem."),
    CatalogLanguage("russian", "Russian", "🇷🇺", "ru", "Standard Russian", "Milena", "Russia and the Russian-speaking world",
                    "Э-э, ну... как бы, короче, это, не знаю."),
    CatalogLanguage("ukrainian", "Ukrainian", "🇺🇦", "uk", "Standard Ukrainian", "Lesya", "Ukraine",
                    "Е-е, ну... тобто, коротше, не знаю."),
    CatalogLanguage("swedish", "Swedish", "🇸🇪", "sv", "Standard Swedish", "Alva", "Sweden",
                    "Öh, alltså... liksom, typ, vet inte."),
    CatalogLanguage("norwegian", "Norwegian", "🇳🇴", "no", "Norwegian Bokmål", "Nora", "Norway",
                    "Eh, altså... liksom, på en måte, vet ikke."),
    CatalogLanguage("danish", "Danish", "🇩🇰", "da", "Standard Danish", "Sara", "Denmark",
                    "Øh, altså... ligesom, du ved, ved ikke."),
    CatalogLanguage("turkish", "Turkish", "🇹🇷", "tr", "Istanbul Turkish", "Yelda", "Turkey",
                    "Şey, yani... işte, hani, ıı, bilmiyorum."),
    CatalogLanguage("greek", "Greek", "🇬🇷", "el", "Standard Modern Greek", "Melina", "Greece and Cyprus",
                    "Εε, δηλαδή... ας πούμε, ξέρεις, δεν ξέρω."),
    CatalogLanguage("japanese", "Japanese", "🇯🇵", "ja", "Standard Japanese (Tokyo)", "Kyoko", "Japan",
                    "えーと、あの…なんか、まあ、わからない。"),
    CatalogLanguage("korean", "Korean", "🇰🇷", "ko", "Standard Korean (Seoul)", "Yuna", "South Korea",
                    "음, 그러니까… 뭐랄까, 저기, 잘 모르겠어요."),
    CatalogLanguage("mandarin", "Mandarin", "🇨🇳", "zh", "Mainland Mandarin (Putonghua)", "Tingting", "China and Taiwan",
                    "嗯，那个…就是，然后，我不知道。"),
    CatalogLanguage("indonesian", "Indonesian", "🇮🇩", "id", "Standard Indonesian", "Damayanti", "Indonesia",
                    "Eh, jadi... gimana ya, anu, nggak tahu."),
    CatalogLanguage("vietnamese", "Vietnamese", "🇻🇳", "vi", "Northern Vietnamese (Hanoi)", "Linh", "Vietnam",
                    "Ờ, thì... kiểu như, à, không biết."),
    CatalogLanguage("hindi", "Hindi", "🇮🇳", "hi", "Standard Hindi", "kokoro:hf_alpha", "India",
                    "अं, मतलब... वो, यानी, पता नहीं।"),
]


def addable_languages() -> list[CatalogLanguage]:
    """Catalog languages that aren't a profile in settings.json yet."""
    added = set(profile_names())
    return [language for language in CATALOG if language.key not in added]


def flag(key: str) -> str:
    return next((language.flag for language in CATALOG if language.key == key), "")


def flag_for_code(code: str) -> str:
    return next((language.flag for language in CATALOG if language.code == code), "")


def add_language(key: str, level: str) -> None:
    """Writes a profile for a catalog language to settings.json."""
    language = next(language for language in CATALOG if language.key == key)
    settings_file = REPO / "settings.json"
    settings = json.loads(settings_file.read_text())
    settings["languages"][key] = {
        "language": language.code,
        "language_name": language.name,
        "variety": language.variety,
        "level": level,
        "voice": language.voice,
        "news_from": language.news_from,
        "whisper_prompt": language.fillers,
    }
    settings_file.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
