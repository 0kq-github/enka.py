import json

import aiohttp
from aiocache import cached

from .exception import ValidateUIDError, UIDNotFounded
from .model import EnkaData
from .model.artifact import Artifact
from .model.character import CharacterSkill, CharacterConstellation, CharacterSkillType


class Enka:
    URL = "https://enka.network/u/{uid}/__data.json"
    REPO_BASE = 'https://raw.githubusercontent.com/Dimbreath/GenshinData/master'
    LANG_URL = REPO_BASE + '/TextMap/TextMap{lang}.json'
    AVATAR_URL = REPO_BASE + '/ExcelBinOutput/AvatarExcelConfigData.json'
    TALENT_URL = REPO_BASE + '/ExcelBinOutput/AvatarTalentExcelConfigData.json'
    SKILL_DEPOT_URL = REPO_BASE + '/ExcelBinOutput/AvatarSkillDepotExcelConfigData.json'
    SKILL_URL = REPO_BASE + '/ExcelBinOutput/AvatarSkillExcelConfigData.json'
    USER_AGENT = "Mozilla/5.0"
    timeout = 30
    """Http connection timeout"""
    proxy = ''
    """Http connection proxy"""
    lang_data = {}
    """Internal language data"""
    avatar_data = {}
    """Internal avatar data"""
    talent_data = {}
    """Internal talent data"""
    skill_depot_data = {}
    """Internal skill pot data"""
    skill_data = {}
    """Internal skill data"""
    lang = 'en'
    """Language for text hash resolve"""

    async def load_lang(self, lang='en'):
        """
        Load language data from Dimbreath repo
        :param lang: language you want to load, default 'en'
        :return:
        """
        async with aiohttp.ClientSession(headers={"User-Agent": self.USER_AGENT}) as client:
            if lang not in self.lang_data:
                resp = await client.get(self.LANG_URL.format(lang=lang.upper()), proxy=self.proxy)
                self.lang_data[lang] = await resp.json(content_type=None)
            if not self.avatar_data:
                resp = await client.get(self.AVATAR_URL, proxy=self.proxy)
                for x in await resp.json(content_type=None):
                    self.avatar_data[x['id']] = x
            if not self.skill_depot_data:
                resp = await client.get(self.SKILL_DEPOT_URL, proxy=self.proxy)
                for x in await resp.json(content_type=None):
                    self.skill_depot_data[x['id']] = x
            if not self.skill_data:
                resp = await client.get(self.SKILL_URL, proxy=self.proxy)
                for x in await resp.json(content_type=None):
                    self.skill_data[x['id']] = x
            if not self.talent_data:
                resp = await client.get(self.TALENT_URL, proxy=self.proxy)
                for x in await resp.json(content_type=None):
                    self.talent_data[x['talentId']] = x

    async def resolve_text_hash(self, text_hash, lang='en'):
        """
        Resolve text hash to actual text
        :param text_hash: text hash
        :param lang: language you want to resolve to
        :return: resolved text
        """
        if lang not in self.lang_data:
            await self.load_lang(lang)
        if not isinstance(text_hash, str):
            text_hash = str(text_hash)
        if text_hash in self.lang_data[lang]:
            return self.lang_data[lang][text_hash]
        else:
            return ''

    @cached(ttl=600)
    async def fetch_user(self, uid: int) -> EnkaData:
        """
        Fetch user data from enka api, resolve text hash if available
        :param uid: user in game uid
        :return: EnkaData oject
        """
        if not isinstance(uid, int):
            try:
                uid = int(uid)
            except ValueError:
                raise ValidateUIDError("Validate UID failed. Please check your UID.")
        if len(str(uid)) != 9 or (100000000 > uid > 999999999):
            raise ValidateUIDError("Validate UID failed. Please check your UID.")

        async with aiohttp.ClientSession(headers={"User-Agent": self.USER_AGENT},
                                         timeout=aiohttp.ClientTimeout(total=self.timeout)) as client:
            resp = await client.get(self.URL.format(uid=uid), proxy=self.proxy)

            if resp.status != 200:
                raise UIDNotFounded(f"UID {uid} not found.")

            data = await resp.json()

            if not data:
                raise UIDNotFounded(f"UID {uid} not found.")

        obj: EnkaData = EnkaData.parse_obj(data)

        for character in obj.characters:
            if character.skill_depot_id in self.skill_depot_data:
                depot = self.skill_depot_data[character.skill_depot_id]
                burst_id = depot['energySkill']
                if burst_id in self.skill_data:
                    cs = CharacterSkill()
                    cs.id = burst_id
                    cs.type = CharacterSkillType.ElementalBurst
                    cs.name_hash = self.skill_data[burst_id]['nameTextMapHash']
                    cs.icon = self.skill_data[burst_id]['skillIcon']
                    character.skills.append(cs)
                for skill_id in depot['skills']:
                    if skill_id and skill_id in self.skill_data:
                        skill_info = self.skill_data[skill_id]
                        cs = CharacterSkill()
                        cs.id = skill_id
                        if 'cdTime' in skill_info and skill_info['cdTime']:
                            cs.type = CharacterSkillType.ElementalSkill
                        else:
                            cs.type = CharacterSkillType.NormalSkill
                        cs.name_hash = skill_info['nameTextMapHash']
                        cs.icon = self.skill_data[burst_id]['skillIcon']
                        character.skills.append(cs)
                for talent_id in depot['talents']:
                    if talent_id and talent_id in self.talent_data:
                        talent_info = self.talent_data[talent_id]
                        tl = CharacterConstellation()
                        tl.id = talent_id
                        tl.icon = talent_info['icon']
                        tl.name_hash = talent_info['nameTextMapHash']
                        character.constellations.append(tl)
                character.process_skill()
                character.activate_constellation()
            if self.lang and self.lang in self.lang_data and self.lang_data[self.lang] and self.avatar_data:
                for equip in character.equipList:
                    equip.flat.nameText = await self.resolve_text_hash(equip.flat.nameTextMapHash, self.lang)
                    if isinstance(equip, Artifact):
                        equip.flat.setNameText = await self.resolve_text_hash(equip.flat.setNameTextMapHash, self.lang)
                if character.id in self.avatar_data:
                    character.name = await self.resolve_text_hash(self.avatar_data[character.id]['nameTextMapHash'],
                                                                  self.lang)
                for skill in character.skills:
                    skill.name = await self.resolve_text_hash(skill.name_hash, self.lang)
                for c in character.constellations:
                    c.name = await self.resolve_text_hash(c.name_hash, self.lang)
        return obj
