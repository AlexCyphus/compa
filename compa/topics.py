"""Everyday topics and how much of each one's vocabulary the learner has actually used, across calls.

A topic counts as covered once the learner has used WORDS_FOR_COVERED topic-specific words in it. Each call picks a
focus topic that isn't covered yet, so over time the calls work through the whole list.
"""
import json
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

WORDS_FOR_COVERED = 30
WORDS_SHOWN_TO_COMPA = 40
RECENT_CALL_DAYS_TO_SKIP = 3

TOPICS = [
    # home and daily life
    "housing and renting", "furniture and decorating", "cleaning and housework", "repairs and DIY", "the garden",
    "neighbours and the building", "moving house", "daily routine", "sleep and dreams", "laundry and clothes care",
    # food
    "cooking and recipes", "the kitchen and utensils", "groceries and the market", "fruit and vegetables",
    "meat and fish", "restaurants and ordering", "coffee and breakfast", "drinks and bars", "baking and desserts",
    "diets and nutrition", "local dishes",
    # people
    "family and relatives", "friendship", "dating and relationships", "weddings", "children and parenting",
    "personality and character", "appearance and the body", "feelings and emotions", "arguments and making up",
    "growing old",
    # health
    "health and the doctor", "illness and symptoms", "the dentist", "hospitals and emergencies", "medicines and the pharmacy",
    "injuries and accidents", "mental health", "fitness and the gym",
    # work and money
    "jobs and careers", "job interviews", "the office", "meetings and presentations", "bosses and colleagues",
    "starting a business", "money and banking", "saving and investing", "taxes and paperwork", "shopping and prices",
    "complaints and returns", "the economy",
    # tech
    "phones and apps", "computers and software", "the internet and social media", "artificial intelligence",
    "video games", "gadgets", "online privacy and scams",
    # getting around
    "cars and driving", "car trouble and the mechanic", "public transport", "bikes", "airports and flying",
    "trains and long journeys", "directions and getting lost", "traffic and city life",
    # travel
    "holidays and travel plans", "hotels and accommodation", "the beach and the sea", "camping", "sightseeing",
    "travel mishaps", "living abroad",
    # nature
    "the weather", "seasons and climate", "the environment and recycling", "animals and wildlife", "pets",
    "farming and the countryside", "mountains and hiking", "rivers, lakes and forests", "natural disasters",
    "plants and flowers",
    # hobbies
    "fishing and hunting", "sport and football", "watching sport", "running and cycling", "swimming and water sports",
    "board games and cards", "music and instruments", "concerts and festivals", "dancing", "photography",
    "drawing and painting", "crafts and sewing", "collecting things", "reading and books", "writing",
    # culture
    "films and series", "theatre", "art and museums", "history", "traditions and holidays", "religion and beliefs",
    "languages and learning", "school", "university and studying", "exams",
    # society
    "politics and elections", "the news", "crime and the police", "the law and courts", "immigration",
    "inequality and poverty", "volunteering and charity", "the military", "public services and bureaucracy",
    # science and ideas
    "science and discoveries", "space and astronomy", "the human brain", "inventions", "the future",
    "philosophy and big questions", "superstitions and luck",
    # everyday situations
    "phone calls and messages", "appointments and plans", "celebrations and parties", "gifts", "childhood memories",
    "fashion and clothes", "hair and beauty", "the post and deliveries", "noise and annoyances", "rules and manners",
]


@dataclass(frozen=True)
class TopicProgress:
    topic: str
    words_used: int
    new_words: int

    @property
    def covered(self) -> bool:
        return self.words_used >= WORDS_FOR_COVERED


class TopicMemory:
    """topics-<lang>.json in the sessions folder: {topic: {"words": [...], "calls": ["2026-11-21", ...]}}."""

    def __init__(self, folder: Path, language: str):
        self.path = folder / f"topics-{language}.json"
        self.topics: dict[str, dict] = json.loads(self.path.read_text()) if self.path.exists() else {}

    def words(self, topic: str) -> list[str]:
        return self.topics.get(topic, {}).get("words", [])

    def progress(self, topic: str, new_words: int = 0) -> TopicProgress:
        return TopicProgress(topic, len(self.words(topic)), new_words)

    def next_topic(self) -> str:
        """A topic not covered yet and not talked about on the last few call days; half-started ones first."""
        recent = self._recent_topics()
        open_topics = [topic for topic in self.all_topics() if not self.progress(topic).covered and topic not in recent]
        started = [topic for topic in open_topics if self.words(topic)]
        return random.choice(started or open_topics or self.all_topics())

    def all_topics(self) -> list[str]:
        return TOPICS + [topic for topic in self.topics if topic not in TOPICS]

    def record(self, topic: str, words: list[str]) -> TopicProgress:
        entry = self.topics.setdefault(topic, {"words": [], "calls": []})
        known = {word.lower() for word in entry["words"]}
        new = [word for word in dict.fromkeys(words) if word.lower() not in known]
        entry["words"] += new
        entry["calls"].append(date.today().isoformat())
        return self.progress(topic, len(new))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.topics, ensure_ascii=False, indent=2))

    def _recent_topics(self) -> set[str]:
        call_dates = sorted({day for entry in self.topics.values() for day in entry["calls"]})[-RECENT_CALL_DAYS_TO_SKIP:]
        return {topic for topic, entry in self.topics.items() if set(entry["calls"]) & set(call_dates)}
