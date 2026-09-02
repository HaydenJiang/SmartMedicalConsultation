#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SmartMedicalConsultation - Web Crawler
Crawl disease information from medical websites (haodf.com, xywy.com)
Follows robots.txt compliance and crawler etiquette
"""

import os
import sys
import json
import time
import random
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse
from typing import Optional
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ===== Configuration =====

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

# Output file
OUTPUT_FILE = DATA_RAW_DIR / "diseases.json"
CHECKPOINT_FILE = DATA_RAW_DIR / ".crawl_checkpoint.json"

# Crawler settings
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15
DELAY_MIN = 3.0  # Minimum delay between requests (seconds)
DELAY_MAX = 5.0  # Maximum delay between requests (seconds)

# Random User-Agent pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ===== Predefined Disease List =====
# Common diseases for medical knowledge graph (haodf.com pinyin slugs).
# 共 500 种，覆盖主要科室，与默认爬取目标 --max 500 对齐。
# 只允许 ASCII 拼音 slug（带音调/连字符的必然 404——URL 里出现非 ASCII 即非法）。
# 无效 slug 是可容忍的：仅计为失败请求，不影响整体（有 xywy 备份源兜底）。
COMMON_DISEASES = [
    # 心血管
    "gaoxueya", "guanxinbing", "xinjiquexue", "xinlvbuqi", "xinzangbing",
    "dongmaizhouyangyinghua", "jingmaiquzhang", "naogengsi", "naochuxue",
    "feidongmaigaoya", "fengshixingxinzangbing", "xinzangbanmobing", "xinzangzaibo",
    # 呼吸
    "ganmao", "liugan", "feiyan", "qiguanyan", "xiaochuan", "manxingzusaixingfeibing",
    "feijiehe", "feiai", "biyan", "yanyan", "guominxingbiyan",
    "shuimianhuxizanting", "manxingzhiqiguanyan",
    # 消化
    "weiyan", "weikuiyang", "ganyan", "ganyinghua", "dangnangyan", "yixianyan",
    "bianmi", "fuxie", "zhichuang", "weichangai", "ganai", "ganglie",
    "xiaohuabuliang", "fushi", "zhifanggan",
    # 内分泌/代谢
    "tangniaobing", "jiazhuangxiankangjin", "jiazhuangxianjiejie", "gaozhixuezheng",
    "tongfeng", "guzhisongshu", "feipangzheng", "jiazhuangxianyan", "jiakang", "jiajian",
    "duonangluanchaozonghezheng",
    # 神经/精神
    "toutong", "touyun", "shimian", "jiaolvzheng", "yiyuzheng",
    "dianxian", "pasenbing", "zhongfeng", "miantan", "shenjingruotong", "zhongjizhengwuli",
    # 骨骼肌肉
    "guzhe", "guanzhijieyan", "guzhizengsheng", "yaotong", "jianzhouyan",
    "jingzhuibing", "qiangzixingjizhuyan", "wangzhuzhouyan",
    # 泌尿
    "shenyan", "shenjieshi", "niaoluganran", "qianliexianyan",
    "qianliexianzengsheng", "niaolujieshi",
    # 皮肤
    "pifuyan", "shizhen", "xunmazhen", "niupixuan", "cuochuang",
    "tuofa", "hongbanlangchuang", "pifuguomin",
    # 眼科
    "jinshi", "yuanzhi", "qingguangyan", "baineizhang", "jiemoyan", "maizhuyan",
    # 耳鼻喉
    "zhongeryan", "houyan", "erming", "erlong", "waieryan",
    # 妇科
    "yuedaoyan", "gongjingyan", "luanchaonangzhong", "zigongjiliu",
    "yuediaobujun", "gongwaiyun",
    # 儿科
    "xiaoerganmao", "xiaoerfashao", "shouzukoubing", "xiaoerfuxie", "xiaoerfeiyan",
    # 肿瘤
    "ruxianai", "linbaliu", "weiai", "changai",
    # 传染病
    "yigan", "binggan", "aizibing", "jiehe", "shuibing",
    # 其他常见
    "pinxue", "guomin", "tangshang", "meiniuer", "zhongshu",
    "kouqiangkuiyang", "yachi", "manxingpilaoyu",
    # 心血管(新增)
    "xinjiaotong", "xinjigengsi", "xinlishuaijie", "xinfangchandong", "xindongguosu",
    "xindongguohuan", "xinjiyan", "xinbaoyan", "ganranxingxinneimoyan", "kuozhangxingxinjibing",
    "feihouxingxinjibing", "zhudongmaijiaceng", "zhudongmailiu", "shenjingmaixueshuan", "feishuanse",
    "xiantianxingxinzangbing", "fangjiangequesun", "shijiangequesun", "dongmaidaoguanweibi", "faluosilianzheng",
    "xinbaojiye", "dixueya", "bingtaidoufangjiezonghezheng", "yujizonghezheng", "erjianbanxiazhai",
    "erjianbanguanbibuquan", "zhudongmaibanxiazhai", "leinuozonghezheng", "xueshuanbisexingmaiguanyan",
    # 呼吸(新增)
    "jixingzhiqiguanyan", "zhiqiguankuozhang", "feiqizhong", "feixinbing", "huxishuaijie",
    "qixiong", "xiongqiangjiye", "feinongzhong", "feixianweihua", "jianzhixingfeiyan",
    "chenfei", "feijiejie", "shanghuxidaoganran", "xiongmoyan", "dayexingfeiyan",
    "zhiyuantifeiyan", "yiyuantifeiyan", "bingduxingfeiyan",
    # 消化(新增)
    "manxingweiyan", "weishiguanfanliubing", "fanliuxingshiguanyan", "shierzhichangkuiyang", "weixirou",
    "changxirou", "keluoenbing", "kuiyangxingjiechangyan", "changyijizonghezheng", "lanweiyan",
    "changgengzu", "fugugoushan", "xiaohuadaochuxie", "shiguanai", "jiechangai",
    "zhichangai", "yixianai", "dannangjieshi", "danguanjieshi", "dannangxirou",
    "youmenluoganjunganran", "xijunxingliji", "weichangyan", "jiujingxingganbing", "yaowuxinggansunshang",
    "ganxueguanliu", "gannangzhong", "ganglou", "manxingdannangyan", "weixiachui",
    # 内分泌(新增)
    "yixingtangniaobing", "erxingtangniaobing", "renshentangniaobing", "tangniaobingzu", "tangniaobingshenbing",
    "tangniaobingshiwangmobingbian", "dixuetang", "qiaobenjiazhuangxianyan", "jiazhuangxianai", "yajixingjiazhuangxianyan",
    "jiazhuangpangxiangongnengkangjin", "kuxinzonghezheng", "shigexibaoliu", "chuitiliu", "zhiduanfeidazheng",
    "niaobengzheng", "daixiezonghezheng", "gaoniaosuanxuezheng", "shenshangxianxianliu", "jiazhuangxiannangzhong",
    "yuanfaxingquangutongzengduozheng", "jiazhuangxianliu",
    # 神经精神(新增)
    "piantoutong", "sanchashenjingtong", "zuogushenjingtong", "naogongxuebuzu", "naoyan",
    "naomoyan", "bingduxingnaoyan", "aercihaimobing", "xueguanxingchidai", "chidai",
    "duofaxingyinghua", "gelinbalizonghezheng", "zhouweishenjingbingbian", "moshaoshenjingyan", "zhiwushenjinggongnengwenluan",
    "qiangpozheng", "kongjuzheng", "chuangshanghouyingjizhangai", "jingshenfenliezheng", "shuangxiangqingganzhangai",
    "zaokuangzheng", "shenjingxingyanshi", "zibizheng", "ertongduodongzheng", "choudongzheng",
    "fazuoxingshuibing", "buningtuizonghezheng", "tefaxingzhenchan", "xuanyun", "mianjijingluan",
    "naojishui", "naotan", "shenjingshuairuo",
    # 骨科(新增)
    "guguanjieyan", "huamoyan", "huanangyan", "jianqiaoyan", "wanguanzonghezheng",
    "zudijinmoyan", "genjianyan", "banyuebansunshang", "rendaisunshang", "guanjietuowei",
    "jianxiusunshang", "yaozhuijianpantuchu", "yaozhuiguanxiazhai", "yaozhuihuatuo", "jizhucewan",
    "gugutouhuaisi", "bianpingzu", "muwaifan", "gurouliu", "gusuiyan",
    "ruanzuzhisunshang", "jiroulashang", "laozhen", "jixingyaoniushang", "jinmoyan",
    "binguruanhuazheng",
    # 风湿免疫(新增)
    "leifengshiguanjieyan", "xitongxinghongbanlangchuang", "ganzaozonghezheng", "yingpibing", "pijiyan",
    "duofaxingjiyan", "xueguanyan", "baisaibing", "dadongmaiyan", "fengshire",
    "xianweijitong",
    # 泌尿(新增)
    "manxingshenyan", "shenbingzonghezheng", "shenshuaijie", "niaoduzheng", "shennangzhong",
    "duonangshen", "shenjishui", "shuniaoguanjieshi", "pangguangjieshi", "pangguangyan",
    "niaodaoyan", "qianliexianai", "shenai", "pangguangai", "gaowanyan",
    "fugaoyan", "jingsuojingmaiquzhang", "baopiguochang", "baojing", "yingao",
    "qiaomojiye", "niaoshijin", "jianzhixingshenyan",
    # 皮肤(新增)
    "daizhuangpaozhen", "danchunpaozhen", "shouzuxuan", "tixuan", "guxuan",
    "jiaxuan", "jiechuang", "maonangyan", "jiezhong", "dandu",
    "fengwozhiyan", "jiechuxingpiyan", "zhiyixingpiyan", "teyingxingpiyan", "shenjingxingpiyan",
    "yaozhen", "duoxinghongban", "meiguikangzhen", "bianpingtaixian", "baidianfeng",
    "huangheban", "queban", "pizhixiannangzhong", "pifusaoyangzheng", "yinxiebing",
    "tianpaochuang", "xunchangyou", "bianpingyou", "jianruishiyou", "exingheisesuliu",
    "hanpaozhen", "banhengeda", "manxingxunmazhen",
    # 眼科(新增)
    "sanguang", "laoshi", "ruoshi", "xieshi", "ganyanzheng",
    "jiaomoyan", "jiaomokuiyang", "yizhuangnurou", "bolitihunzhuo", "feiwenzheng",
    "shiwangmotuoluo", "huangbanbianxing", "shishenjingyan", "putaomoyan", "shayan",
    "guominxingjiemoyan", "jianyuanyan", "daojie", "leinangyan", "yanwaishang",
    "yuanzhuijiaomo",
    # 耳鼻喉(新增)
    "bidouyan", "bixirou", "bizhonggepianqu", "bichuxie", "shengdaixirou",
    "shengdaixiaojie", "biantaotiyan", "manxingyanyan", "jixingyanyan", "xianyangtifeida",
    "fenmixingzhongeryan", "huanongxingzhongeryan", "gumochuankong", "tufaxingerlong", "yundongbing",
    "qiantingshenjingyan", "liangxingzhenfaxingweizhixingxuanyun", "biyanai",
    # 妇科(新增)
    "penqiangyan", "fujianyan", "zigongneimoyan", "zigongneimoyiweizheng", "zigongxianjizheng",
    "zigongneimoai", "gongjingai", "luanchaoai", "waiyinyan", "meijunxingyindaoyan",
    "dichongxingyindaoyan", "bijing", "tongjing", "jingqianqizonghezheng", "gengnianqizonghezheng",
    "gongnengshitiaoxingzigongchuxie", "zigongtuochui", "buyunzheng", "xiguanxingliuchan", "renshengaoxueya",
    "qianzhitaipan", "taipanzaobo", "chanhouchuxie", "ruxianzengsheng", "ruxianyan",
    "ruxianxianweiliu", "ruxianjiejie", "chanhouyiyu",
    # 儿科(新增)
    "xinshengerhuangdan", "xinshengerfeiyan", "xiaoerxiaochuan", "xiaoerzhiqiguanyan", "xiaoerbianmi",
    "xiaoeryanshi", "xiaoeryingyangbuliang", "xiaoernaotan", "gouloubing", "xiaoershanqi",
    "xiaoerchangtaodie", "chuanqibing", "xiaoeryiniao", "aixiaozheng", "xingzaoshu",
    "yingershizhen", "xiaoerjingfeng", "xinshengerbaixuezheng",
    # 肿瘤(新增)
    "naoliu", "baixuebing", "duofaxinggusuiliu", "zhifangliu", "xueguanliu",
    "jitailiu", "shenjingmuxibaoliu", "shiwangmomuxibaoliu", "naomoliu", "tingshenjingliu",
    # 传染病(新增)
    "jiagan", "wugan", "mazhen", "fengzhen", "xinghongre",
    "bairike", "liuxingxingsaixianyan", "yixingnaoyan", "nueji", "shanghan",
    "kuangquanbing", "poshangfeng", "meidu", "linbing", "shengzhiqipaozhen",
    "huichongbing", "gongxingchongbing", "naochongbing",
    # 血液(新增)
    "quetiexingpinxue", "juyouxibaoxingpinxue", "zaishengzhangaixingpinxue", "rongxuexingpinxue", "dizhonghaipinxue",
    "guominxingzidian", "xuexiaobanjianshaoxingzidian", "xuexiaobanjianshaozheng", "xueyoubing", "gusuizengshengyichangzonghezheng",
    "zhenxinghongxibaozengduozheng", "pigongnengkangjin",
    # 口腔(新增)
    "yazhouyan", "yayinyan", "quchi", "yasuiyan", "genjianzhouyan",
    "zhichiguanzhouyan", "ekouchuang", "niexiaheguanjiewenluan", "kouchou", "moyazheng",
    # 男科(新增)
    "yangwei", "zaoxie", "nanxingbuyu", "xinggongnengzhangai", "yijing",
    "guitouyan",
    # 普外及其他(新增)
    "shanqi", "danchunxingjiazhuangxianzhong", "linbajieyan", "shaoshang", "dongshang",
    "ruchuang", "yajiankang", "dijiaxuezheng", "baixuezheng", "changzhanlian",
]


# Generate full URLs from disease IDs (deduplicated, order preserved)
def get_predefined_urls() -> list:
    """Generate full haodf.com URLs from predefined disease slugs"""
    seen, urls = set(), []
    for disease_id in COMMON_DISEASES:
        if disease_id in seen:
            continue
        seen.add(disease_id)
        urls.append(f"https://www.haodf.com/citiao/jibing-{disease_id}.html")
    return urls

# ===== Logging Setup =====

log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "crawler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ===== Robots.txt Checker =====

class RobotsChecker:
    """Check if a URL is allowed by robots.txt"""

    def __init__(self):
        self.parsers = {}

    def get_parser(self, base_url: str) -> RobotFileParser:
        """Get or create a robots.txt parser for a domain"""
        if base_url not in self.parsers:
            rp = RobotFileParser()
            robots_url = urljoin(base_url, "/robots.txt")
            rp.set_url(robots_url)
            try:
                rp.read()
                logger.info(f"[OK] Loaded robots.txt from {robots_url}")
            except Exception as e:
                logger.warning(f"[WARN] Failed to load robots.txt from {robots_url}: {e}")
                # If we can't read robots.txt, allow everything (be conservative)
                rp.allow_all = True
            self.parsers[base_url] = rp
        return self.parsers[base_url]

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Check if a URL is allowed by robots.txt"""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        rp = self.get_parser(base_url)

        if hasattr(rp, "allow_all"):
            return True

        return rp.can_fetch(user_agent, url)

    def get_crawl_delay(self, base_url: str, user_agent: str = "*") -> Optional[float]:
        """Get the crawl delay specified in robots.txt"""
        rp = self.get_parser(base_url)
        try:
            delay = rp.crawl_delay(user_agent)
            return float(delay) if delay else None
        except Exception:
            return None


# ===== Crawler Class =====

class MedicalCrawler:
    """Crawl disease information from medical websites"""

    def __init__(self):
        self.session = requests.Session()
        self.robots_checker = RobotsChecker()
        self.crawled_urls = set()
        self.diseases = []
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }
        self._load_checkpoint()

    def _get_headers(self) -> dict:
        """Get random headers for each request"""
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    def _delay(self):
        """Wait a random delay between requests"""
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        time.sleep(delay)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
    )
    def _fetch(self, url: str) -> Optional[str]:
        """Fetch a URL with retry logic"""
        # Check robots.txt first
        if not self.robots_checker.is_allowed(url):
            logger.warning(f"[BLOCKED] robots.txt disallows: {url}")
            return None

        logger.info(f"[FETCH] {url}")
        response = self.session.get(
            url,
            headers=self._get_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def _load_checkpoint(self):
        """Load checkpoint to resume crawling"""
        if CHECKPOINT_FILE.exists():
            try:
                with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.crawled_urls = set(data.get("crawled_urls", []))
                self.diseases = data.get("diseases", [])
                self.stats = data.get("stats", self.stats)
                logger.info(
                    f"[RESUME] Loaded checkpoint: {len(self.crawled_urls)} URLs crawled, "
                    f"{len(self.diseases)} diseases collected"
                )
            except Exception as e:
                logger.warning(f"[WARN] Failed to load checkpoint: {e}")

    def _save_checkpoint(self):
        """Save checkpoint for resume"""
        try:
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "crawled_urls": list(self.crawled_urls),
                        "diseases": self.diseases,
                        "stats": self.stats,
                        "timestamp": datetime.now().isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"[ERROR] Failed to save checkpoint: {e}")

    def _save_results(self):
        """Save final results to JSON"""
        try:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "metadata": {
                            "source": "haodf.com + xywy.com",
                            "crawled_at": datetime.now().isoformat(),
                            "total_diseases": len(self.diseases),
                        },
                        "diseases": self.diseases,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info(f"[SAVED] {len(self.diseases)} diseases saved to {OUTPUT_FILE}")
        except Exception as e:
            logger.error(f"[ERROR] Failed to save results: {e}")

    # ===== Haodf.com Crawlers =====

    def crawl_haodf_list(self) -> list:
        """Crawl disease list from haodf.com

        Note: The list page only shows ~15 popular diseases.
        For a complete list, we would need to crawl the sitemap
        or use a different approach (e.g., department-based crawling).
        """
        logger.info("=" * 60)
        logger.info("[START] Crawling haodf.com disease list")
        logger.info("=" * 60)

        disease_urls = []
        list_url = "https://www.haodf.com/jibing/"

        try:
            html = self._fetch(list_url)
            if not html:
                return disease_urls

            soup = BeautifulSoup(html, "html.parser")

            # Find all disease links with pattern: jibing-<disease_id>
            # These appear as: //www.haodf.com/citiao/jibing-gaoxueya/tuijian-doctor.html
            import re
            all_hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]

            for href in all_hrefs:
                # Match pattern: jibing-<disease_id>/
                match = re.search(r'jibing-([^/]+)', href)
                if match:
                    disease_id = match.group(1)
                    # Construct the detail URL
                    detail_url = f"https://www.haodf.com/citiao/jibing-{disease_id}.html"
                    if detail_url not in self.crawled_urls and detail_url not in disease_urls:
                        disease_urls.append(detail_url)

            logger.info(f"[LIST] Found {len(disease_urls)} disease URLs from haodf.com")
            logger.info(f"[INFO] Note: haodf.com list page only shows ~15 popular diseases")

        except Exception as e:
            logger.error(f"[ERROR] Failed to crawl disease list: {e}")

        return disease_urls

    def crawl_haodf_detail(self, url: str) -> Optional[dict]:
        """Crawl disease detail from haodf.com

        URL format: https://www.haodf.com/citiao/jibing-<disease_id>.html
        """
        try:
            html = self._fetch(url)
            if not html:
                return None

            soup = BeautifulSoup(html, "html.parser")
            disease = {"source": "haodf.com", "url": url, "crawled_at": datetime.now().isoformat()}

            # Extract disease name from H1
            h1_tag = soup.find("h1")
            if h1_tag:
                disease["name"] = h1_tag.get_text(strip=True)
            else:
                # Fallback to title
                title_tag = soup.find("title")
                if title_tag:
                    # Title format: "高血压 - 好大夫在线"
                    title_text = title_tag.get_text(strip=True)
                    disease["name"] = title_text.split(" - ")[0].strip() if " - " in title_text else title_text

            # Extract department from page content
            # Look for department info in the page
            page_text = soup.get_text()
            import re

            # Try to find department info (e.g., "心血管内科")
            # 科室信息：优先显式"就诊科室："标签。
            # 注意：通用 r'([^\s]+科)' 会误匹配"就诊科"三个字（首见于"就诊科室"），已移除。
            dept_patterns = [
                r'就诊科室[：:]\s*([^\n，。;；]{2,15})',
                r'科室[：:]\s*([^\n，。;；]{2,15})',
            ]
            for pattern in dept_patterns:
                match = re.search(pattern, page_text)
                if match:
                    dept = match.group(1).strip()
                    if dept and "就诊科室" not in dept:
                        disease["department"] = dept
                        break

            # 描述：优先取最长正文 <p> 段（排除导航/推广文案），
            # 退路：带 class 的内容容器
            boilerplate = ("好大夫", "copyright", "预约挂号", "电话咨询", "版权所有", "在线问诊")
            best = ""
            for tag in soup.find_all("p"):
                txt = tag.get_text(strip=True)
                if 80 <= len(txt) <= 600 and len(txt) > len(best) \
                        and not any(k in txt for k in boilerplate):
                    best = txt
            if not best:
                for section in soup.find_all(["div", "section"], class_=True):
                    txt = section.get_text(strip=True)
                    if 50 < len(txt) < 500 and not any(k in txt for k in boilerplate):
                        best = txt
                        break
            if best:
                disease["description"] = best[:500]

            # Extract symptoms
            symptoms = []
            symptom_patterns = [
                r'常见症状[：:]\s*([^\n]+)',
                r'主要症状[：:]\s*([^\n]+)',
                r'临床表现[：:]\s*([^\n]+)',
                r'症状[：:]\s*([^\n]+)',
            ]
            for pattern in symptom_patterns:
                match = re.search(pattern, page_text)
                if match:
                    symptom_text = match.group(1)
                    # Split by common delimiters
                    symptoms = [s.strip() for s in re.split(r'[、，,]', symptom_text) if s.strip()]
                    break

            disease["symptoms"] = symptoms[:10]  # Limit to 10 symptoms

            # Extract treatment info
            treatment_patterns = [
                r'治疗[：:]\s*([^\n]+)',
                r'治疗方法[：:]\s*([^\n]+)',
            ]
            for pattern in treatment_patterns:
                match = re.search(pattern, page_text)
                if match:
                    disease["treatment"] = match.group(1).strip()[:300]
                    break

            return disease

        except Exception as e:
            logger.error(f"[ERROR] Failed to crawl {url}: {e}")
            return None

    # ===== XYWY.com Crawlers (Backup) =====

    def crawl_xywy_list(self) -> list:
        """Crawl disease list from xywy.com as backup source.

        站点已迁移：疾病条目现位于 zzk.xywy.com/{id}_gaishu.html，
        jib.xywy.com 首页仍索引 100+ 条，从中发现。
        """
        logger.info("=" * 60)
        logger.info("[START] Crawling xywy.com disease list (backup source)")
        logger.info("=" * 60)

        disease_urls = []
        list_url = "https://jib.xywy.com/"

        try:
            html = self._fetch(list_url)
            if not html:
                return disease_urls

            import re
            ids = set(re.findall(r"(?:https?:)?//zzk\.xywy\.com/(\d+_gaishu\.html)", html))
            disease_urls = [
                f"https://zzk.xywy.com/{page_id}"
                for page_id in sorted(ids)
                if f"https://zzk.xywy.com/{page_id}" not in self.crawled_urls
            ]
            logger.info(f"[LIST] Found {len(disease_urls)} disease URLs from xywy.com (zzk)")

        except Exception as e:
            logger.error(f"[ERROR] Failed to crawl xywy.com list: {e}")

        return disease_urls

    def crawl_xywy_detail(self, url: str) -> Optional[dict]:
        """Crawl disease/symptom detail from zzk.xywy.com（{id}_gaishu.html）

        页面无 h1，疾病名取自 <title> 首段（如「头痛怎么办_原因_检查_..._寻医问药网」）；
        正文含 就诊科室 / 相关症状 / 相关检查 / 治疗 等可正则定位的结构化片段。
        """
        try:
            html = self._fetch(url)
            if not html:
                return None

            import re
            soup = BeautifulSoup(html, "html.parser")
            disease = {"source": "xywy.com", "url": url, "crawled_at": datetime.now().isoformat()}

            # 名称：<title> 首段去掉「怎么办/是怎么回事/...」尾巴
            title_tag = soup.find("title")
            if title_tag:
                seg = title_tag.get_text(strip=True).split("_")[0]
                disease["name"] = re.sub(r"(怎么办|是怎么回事|是什么原因|是什么病)$", "", seg).strip()
            if not disease.get("name"):
                h1 = soup.find("h1")
                if h1:
                    disease["name"] = h1.get_text(strip=True)
            if not disease.get("name"):
                return None

            page_text = soup.get_text()

            # 就诊科室（取首个出现，截断到下一个栏目标签）
            m = re.search(
                r"就诊科室[：:]\s*([^\n]{1,40}?)(?:相关检查|相关症状|温馨提示|\s{2,}|$)",
                page_text,
            )
            if m:
                disease["department"] = m.group(1).strip().rstrip("，。、 ")

            # 症状列表（相关症状优先，其次常见症状）
            m = (
                re.search(r"相关症状\s+(.{1,120}?)\s*温馨提示", page_text)
                or re.search(r"常见症状[：:]?\s*([^\n]{1,120})", page_text)
            )
            if m:
                symptoms = [
                    s.strip()
                    for s in re.split(r"[、，,\s]+", m.group(1))
                    if 1 < len(s.strip()) <= 12
                ]
                disease["symptoms"] = symptoms[:10]

            # 相关检查（并入治疗字段，供抽取器使用）
            checks = None
            m = re.search(
                r"相关检查[：:]\s*([^\n]{1,120}?)(?:温馨提示|相关症状|\s{2,}|$)",
                page_text,
            )
            if m:
                checks = m.group(1).strip().rstrip("，。、 ")

            # 治疗文本（关键词后首个像句子的片段）
            treatment = ""
            m = re.search(r"治疗[^：:\n]{0,6}[：:]?\s*([^\n]{10,300})", page_text)
            if m:
                treatment = m.group(1).strip()
            if checks:
                treatment = (
                    f"{treatment}；相关检查：{checks}" if treatment else f"相关检查：{checks}"
                )
            if treatment:
                disease["treatment"] = treatment[:400]

            # 描述：首个 50–500 字的正文段落
            for block in soup.get_text("\n").split("\n"):
                block = block.strip()
                if 50 < len(block) < 500 and block != disease.get("name"):
                    disease["description"] = block
                    break

            return disease

        except Exception as e:
            logger.error(f"[ERROR] Failed to crawl {url}: {e}")
            return None

    # ===== Main Crawl Logic =====

    def run(self, max_diseases: int = 500, use_backup: bool = True, use_predefined: bool = True):
        """
        Run the crawler

        Args:
            max_diseases: Maximum number of diseases to crawl
            use_backup: Whether to use xywy.com as backup source (default ON,
                        needed to reach large --max targets)
            use_predefined: Whether to use predefined disease list (recommended)
        """
        logger.info("=" * 60)
        logger.info(f"[START] Medical Crawler started at {datetime.now().isoformat()}")
        logger.info(f"[CONFIG] Max diseases: {max_diseases}, Backup: {use_backup}, Predefined: {use_predefined}")
        logger.info("=" * 60)

        # Step 1: URLs = 预定义列表 ∪ 列表页发现（去重、保序），两路互补
        if use_predefined:
            predefined_urls = get_predefined_urls()
            logger.info(f"[LIST] Predefined disease list: {len(predefined_urls)} slugs")
            list_urls = self.crawl_haodf_list()
            haodf_urls = list(dict.fromkeys(predefined_urls + list_urls))
            logger.info(f"[LIST] Total haodf URLs (predefined + list page): {len(haodf_urls)}")
        else:
            # Fallback: crawl from haodf.com list page only
            haodf_urls = self.crawl_haodf_list()

        for url in haodf_urls:
            if len(self.diseases) >= max_diseases:
                break

            if url in self.crawled_urls:
                self.stats["skipped"] += 1
                continue

            disease = self.crawl_haodf_detail(url)
            if disease and disease.get("name"):
                self.diseases.append(disease)
                self.crawled_urls.add(url)
                self.stats["success"] += 1
                logger.info(
                    f"[OK] [{len(self.diseases)}/{max_diseases}] "
                    f"{disease['name']} - {len(disease.get('symptoms', []))} symptoms"
                )
            else:
                self.stats["failed"] += 1

            self.stats["total"] += 1
            self._save_checkpoint()
            self._delay()

        # Step 2: Crawl from xywy.com (backup source)
        if use_backup and len(self.diseases) < max_diseases:
            xywy_urls = self.crawl_xywy_list()

            for url in xywy_urls:
                if len(self.diseases) >= max_diseases:
                    break

                if url in self.crawled_urls:
                    self.stats["skipped"] += 1
                    continue

                disease = self.crawl_xywy_detail(url)
                if disease and disease.get("name"):
                    self.diseases.append(disease)
                    self.crawled_urls.add(url)
                    self.stats["success"] += 1
                    logger.info(
                        f"[OK] [{len(self.diseases)}/{max_diseases}] "
                        f"{disease['name']} (xywy)"
                    )
                else:
                    self.stats["failed"] += 1

                self.stats["total"] += 1
                self._save_checkpoint()
                self._delay()

        # Step 3: Save results
        self._save_results()

        # Step 4: Print summary
        logger.info("=" * 60)
        logger.info("[COMPLETE] Crawl Summary:")
        logger.info(f"  Total requests: {self.stats['total']}")
        logger.info(f"  Success: {self.stats['success']}")
        logger.info(f"  Failed: {self.stats['failed']}")
        logger.info(f"  Skipped (already crawled): {self.stats['skipped']}")
        logger.info(f"  Diseases collected: {len(self.diseases)}")
        logger.info(f"  Output: {OUTPUT_FILE}")
        logger.info("=" * 60)


# ===== Main Entry =====

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Medical Website Crawler")
    parser.add_argument(
        "--max", type=int, default=500, help="Maximum number of diseases to crawl (default: 500)"
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="Disable xywy.com backup source (backup is ON by default to reach large --max targets)",
    )
    parser.add_argument(
        "--reset", action="store_true", help="Reset checkpoint and start fresh"
    )
    parser.add_argument(
        "--no-predefined", action="store_true",
        help="Don't use predefined disease list (crawl from website list page only)"
    )

    args = parser.parse_args()

    if args.reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("[RESET] Checkpoint file deleted, starting fresh")

    crawler = MedicalCrawler()
    crawler.run(
        max_diseases=args.max,
        use_backup=not args.no_backup,
        use_predefined=not args.no_predefined
    )


if __name__ == "__main__":
    main()
