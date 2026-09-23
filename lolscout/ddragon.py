"""Datos estáticos oficiales (Data Dragon): versión del parche, campeones, ítems, runas, hechizos.
No necesita API key. Se cachea en data/ddragon/<versión>/."""
import json
import re

import requests

from . import config

BASE = "https://ddragon.leagueoflegends.com"


class DDragon:
    def __init__(self, version: str = None, offline: bool = False):
        self.cache = config.DATA_DIR / "ddragon"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.version = version or self._latest_version(offline)
        self.champions = {}   # id numérico -> {name, key(img)}
        self.items = {}       # id -> {name, completed}
        self.runes = {}       # id -> name
        self.rune_slots = {}  # id de árbol -> [conjunto de runas de cada ranura]
        self.rune_style = {}  # id de runa -> id de su árbol
        self.spells = {}      # id -> {name, image}
        self.champ_by_alias = {}  # "Kaisa" / "kaisa" -> id numérico (para la API en vivo)
        self._load()

    @property
    def patch(self) -> str:
        return ".".join(self.version.split(".")[:2])

    def _latest_version(self, offline: bool) -> str:
        f = self.cache / "version.txt"
        if offline and f.exists():
            return f.read_text().strip()
        try:
            v = requests.get(f"{BASE}/api/versions.json", timeout=15).json()[0]
            f.write_text(v)
            return v
        except Exception:
            if f.exists():
                return f.read_text().strip()
            raise

    def _fetch(self, name: str, lang: str = None):
        lang = lang or config.LANGUAGE
        folder = self.cache / self.version / lang
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / name
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        url = f"{BASE}/cdn/{self.version}/data/{lang}/{name}"
        data = requests.get(url, timeout=30).json()
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def _load(self):
        for c in self._fetch("champion.json")["data"].values():
            cid = int(c["key"])
            self.champions[cid] = {"name": c["name"], "img": c["image"]["full"], "tags": c["tags"],
                                   "alias": c["id"], "info": c.get("info", {}), "stats": c.get("stats", {})}
            self.champ_by_alias[c["id"].lower()] = cid
            self.champ_by_alias[c["name"].lower()] = cid

        try:  # habilidades y pasivas (para leer qué hace cada campeón)
            full = self._fetch("championFull.json", "en_US")["data"]
            for c in full.values():
                cid = int(c["key"])
                if cid in self.champions:
                    self.champions[cid]["kit"] = self._kit(c)
                    self.champions[cid]["ranged"] = c.get("stats", {}).get("attackrange", 125) >= 300
        except Exception:
            pass

        en_items = self._fetch("item.json", "en_US")["data"]

        for iid, it in self._fetch("item.json")["data"].items():
            gold = it.get("gold", {})
            tags = it.get("tags", [])
            boots = "Boots" in tags and it.get("depth", 1) >= 2
            final = not it.get("into") and gold.get("total", 0) >= 1600
            support = "GoldPer" in tags and not it.get("into") and it.get("depth", 1) >= 3
            consumable = "Consumable" in tags or "Trinket" in tags or not it.get("maps", {}).get("11", True)
            self.items[int(iid)] = {
                "name": it["name"],
                "img": it["image"]["full"],
                "completed": (boots or final or support) and not consumable,
                "boots": boots,
                "gold": gold.get("total", 0),
                "stats": it.get("stats", {}),
                "tags": self._situational_tags(en_items.get(iid, it)),
                "full": self._parse_stats(en_items.get(iid, it)),
                "from": [int(x) for x in it.get("from", [])],
                # los ítems con número de 6 cifras son copias para otros modos (Arena, etc.): en la
                # Grieta no se pueden comprar aunque el archivo diga que sí
                "sr": int(iid) < 10000 and it.get("maps", {}).get("11", True) and gold.get("purchasable", True),
                "depth": it.get("depth", 1),
            }

        for style in self._fetch("runesReforged.json"):
            self.rune_slots[style["id"]] = []
            for slot in style["slots"]:
                self.rune_slots[style["id"]].append({r["id"] for r in slot["runes"]})
                for rune in slot["runes"]:
                    self.runes[rune["id"]] = {"name": rune["name"], "icon": rune["icon"]}
                    self.rune_style[rune["id"]] = style["id"]
            self.runes[style["id"]] = {"name": style["name"], "icon": style["icon"]}

        for s in self._fetch("summoner.json")["data"].values():
            self.spells[int(s["key"])] = {"name": s["name"], "img": s["image"]["full"]}

    @staticmethod
    def _kit(c) -> dict:
        """Qué hace el campeón según su pasiva y sus habilidades (texto oficial en inglés)."""
        def clean(t):
            return re.sub(r"\s+", " ", re.sub(r"\{\{[^}]*\}\}|<[^>]+>", " ", t or ""))
        parts = [clean(c.get("passive", {}).get("description", ""))]
        parts += [clean(sp.get("description", "")) + " " + clean(sp.get("tooltip", "")) for sp in c.get("spells", [])]
        text = " ".join(parts)
        low = text.lower()
        # de qué tipo es el daño del campeón, según cómo lo describe el juego
        mag = len(re.findall(r"magic damage", low))
        phy = len(re.findall(r"physical damage", low))
        dmgtype = "magic" if mag > phy * 1.4 else "physical" if phy > mag * 1.4 else None
        cc_words = ("stun", "knock", "pull", "root", "immobiliz", "charm", "fear", "taunt", "suppress", "sleep",
                    "airborne", "polymorph", "imprison", "knocks up", "grounded")
        cc = sum(1 for p in parts[1:] if any(w in p.lower() for w in cc_words))
        return {
            "heal": bool(re.search(r"\bheal(?!th)|restores? [^.]{0,40}health|steals? life|siphons? life|omnivamp|"
                                   r"life steal|drains? (?:life|health)", low.replace("healing reduction", ""))),
            "shield": bool(re.search(r"(?:gains?|grants?|creates?|receives?|provides?)[^.]{0,30}\bshield\b|"
                                     r"\bshields? (?:allies|an ally|himself|herself|itself|themselves|nearby)|absorbs? damage", low)),
            "true": "true damage" in low,
            "maxhp": bool(re.search(r"maximum health|max health|percentage of the target's|% of the target's", low)),
            "invis": bool(re.search(r"invisib|camouflage|stealth", low)),
            "untargetable": "untargetable" in low,
            "cc": cc,
            "dash": bool(re.search(r"\bdash|leaps?\b|blink|tumble|teleports? to", low)),
            "as_scaling": "attack speed" in low,
            "hp_scaling": bool(re.search(r"bonus health", low)),
            "dmgtype": dmgtype,
        }

    STAT_NAMES = {
        "Attack Damage": "ad", "Ability Power": "ap", "Attack Speed": "as", "Critical Strike Chance": "crit",
        "Lethality": "leth", "Armor Penetration": "arpen", "Magic Penetration": "mpen", "Health": "hp",
        "Armor": "armor", "Magic Resist": "mr", "Ability Haste": "ah", "Move Speed": "ms", "Life Steal": "ls",
        "Omnivamp": "ov", "Heal and Shield Power": "hsp", "Mana": "mana", "Tenacity": "ten",
        "Base Mana Regen": "mregen", "Base Health Regen": "hregen",
    }

    @classmethod
    def _parse_stats(cls, item: dict) -> dict:
        """Todas las estadísticas del ítem (incluye letalidad, penetración, etc., que no vienen en 'stats')."""
        desc = item.get("description", "")
        m = re.search(r"<stats>(.*?)</stats>", desc, re.S)
        out = {}
        if not m:
            return out
        for line in re.split(r"<br\s*/?>", m.group(1)):
            line = re.sub(r"<[^>]+>", " ", line).strip()
            mm = re.match(r"([\d.]+)(%?)\s+(.+)", line)
            if mm and mm.group(3).strip() in cls.STAT_NAMES:
                out[cls.STAT_NAMES[mm.group(3).strip()]] = float(mm.group(1))
        return out

    @staticmethod
    def _situational_tags(item: dict) -> set:
        """Para qué sirve un ítem, deducido de sus estadísticas y su descripción oficial en inglés."""
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", item.get("description", "")))
        stats = item.get("stats", {})
        tags = set()
        if "Wounds" in text: tags.add("antiheal")
        if "Armor Penetration" in text or "Lethality" in text: tags.add("armorpen")
        if "Magic Penetration" in text: tags.add("magicpen")
        if stats.get("FlatSpellBlockMod"): tags.add("vs_ap")
        if stats.get("FlatArmorMod"): tags.add("vs_ad")
        if any(k in text for k in ("Stasis", "Lifeline", "Rebirth")): tags.add("antiburst")
        if "Quicksilver" in text or "Tenacity" in text: tags.add("anticc")
        if "less damage from Critical" in text: tags.add("anticrit")
        if stats.get("PercentLifeStealMod") or "Omnivamp" in text or "Heal and Shield Power" in text:
            tags.add("heals")
        if "Giant Slayer" in text or "max Health" in text or "current Health" in text: tags.add("vs_tank")
        if "reduces the target's Armor" in text or "Armor Penetration" in text or "Lethality" in text:
            tags.add("armorpen")
        if "take" in text and "more magic damage" in text: tags.add("magicpen")
        if "Shield Reaver" in text: tags.add("antishield")
        if "Reduce the Attack Speed" in text: tags.add("antias")
        if "Spell Shield" in text or "Ignore Pain" in text: tags.add("antiburst")
        if "Lifeline" in text: tags.add("lifeline")
        if "Quicksilver" in text: tags.add("qss")
        if re.search(r"\d+%\s*(?:<[^>]+>\s*)*Armor Penetration", item.get("description", "")): tags.add("lastwhisper")
        return tags

    def champ_from_live(self, raw_name: str = "", display: str = ""):
        """La API en vivo da 'game_character_displayname_Kaisa' y el nombre visible."""
        alias = raw_name.rsplit("_", 1)[-1].lower() if raw_name else ""
        return self.champ_by_alias.get(alias) or self.champ_by_alias.get(display.lower())

    # Helpers de nombres / imágenes
    def champ_name(self, cid): return self.champions.get(cid, {}).get("name", f"#{cid}")
    def item_name(self, iid): return self.items.get(iid, {}).get("name", f"#{iid}")
    def rune_name(self, rid): return self.runes.get(rid, {}).get("name", f"#{rid}")
    def spell_name(self, sid): return self.spells.get(sid, {}).get("name", f"#{sid}")

    def champ_img(self, cid):
        img = self.champions.get(cid, {}).get("img")
        return f"{BASE}/cdn/{self.version}/img/champion/{img}" if img else ""

    def item_img(self, iid):
        img = self.items.get(iid, {}).get("img")
        return f"{BASE}/cdn/{self.version}/img/item/{img}" if img else ""

    def rune_img(self, rid):
        icon = self.runes.get(rid, {}).get("icon")
        return f"{BASE}/cdn/img/{icon}" if icon else ""

    def spell_img(self, sid):
        img = self.spells.get(sid, {}).get("img")
        return f"{BASE}/cdn/{self.version}/img/spell/{img}" if img else ""
