from django.core.management.base import BaseCommand

from pages.models import (
    FiveElementOption,
    FiveElementOptionScore,
    FiveElementProfile,
    FiveElementProfileProduct,
    FiveElementQuestion,
    FiveElementQuiz,
)
from products.models import Category, Product


QUIZ_CONFIG = {
    "name": "五行情绪人格测试",
    "slug": "five-elements",
    "title": "测试你的五行人格与当下仪式路径",
    "subtitle": "先理解你的情绪，再推荐适合你的仪式物。",
    "intro_title": "不是判断你是谁，而是看见你此刻需要什么。",
    "intro_body": "这套测试围绕你当下的情绪、节奏与恢复方式，帮助你找到更适合自己的五行仪式路径。我们先命名你的状态，再给出主符号、仪式物与氛围/承接物。",
    "estimated_minutes": 5,
    "sort_order": 10,
    "is_active": True,
}

PROFILE_CONFIGS = [
    {
        "code": FiveElementProfile.ElementCode.WOOD,
        "name": "木",
        "theme_word": "生长",
        "emotion_title": "你现在更需要的，不是被催促，而是重新开始生长。",
        "emotion_body": "你也许并不缺行动力，你只是需要一个允许自己慢慢展开、逐渐长出方向的环境。先被理解，再重新开始。",
        "result_title": "你的主导五行是木",
        "short_description": "木不是更快向前，而是让内在重新恢复生成感。",
        "long_description": "你此刻更适合的，不是再被推着往前走，而是回到一种有呼吸、有空间、有展开可能性的状态。木对应的是生长：不是立刻证明什么，而是让自己重新长出来。",
        "primary_symbol_title": "绿幽灵吊坠 / 项链",
        "primary_symbol_description": "它像枝叶、雾气与生成过程被封存在晶体里，让你的状态先被看见。它不是一个绿色商品，而是“重新生长”的主符号。",
        "ritual_object_title": "书写本 / Journal",
        "ritual_object_description": "当模糊感受被写下来，内在的变化才会慢慢显形。书写不是记录任务，而是让自己被重新看见。",
        "ambient_object_title": "扩香木 / 木系精油",
        "ambient_object_description": "把木的主题从佩戴延伸到呼吸与空间，让“生长”变成一种可被感知的氛围。",
        "sort_order": 10,
    },
    {
        "code": FiveElementProfile.ElementCode.FIRE,
        "name": "火",
        "theme_word": "回温",
        "emotion_title": "你现在更需要的，不是更强烈，而是慢慢回温。",
        "emotion_body": "你可能已经撑了很久，所以此刻需要的不是再被点燃一次，而是让身体、情绪与生命力重新恢复温度。",
        "result_title": "你的主导五行是火",
        "short_description": "火不是过度燃烧，而是把生命热度慢慢找回来。",
        "long_description": "你此刻适合的是温度、循环与重新连上自己。火对应的是回温：从麻木、迟钝或冷却里，重新回到一种有热、有流动、有回应的状态。",
        "primary_symbol_title": "石榴石吊坠 / 项链",
        "primary_symbol_description": "深红、血色、余烬里的热，承接成熟感与生命力。它不是红色饰品，而是“回温”的主符号。",
        "ritual_object_title": "肉桂精油",
        "ritual_object_description": "把抽象的火感变成身体能够感知的温度，让你先从冷下来的状态里回来。",
        "ambient_object_title": "扩香木 / 香气仪式物",
        "ambient_object_description": "让温度从个体延伸到空间，帮助回温变成一种可停留的氛围。",
        "sort_order": 20,
    },
    {
        "code": FiveElementProfile.ElementCode.EARTH,
        "name": "土",
        "theme_word": "承托",
        "emotion_title": "你现在更需要的，不是更用力，而是先被稳稳承托。",
        "emotion_body": "当一个人太久都在自己撑住自己，最稀缺的往往不是意志，而是那种被托住、能站稳的感觉。",
        "result_title": "你的主导五行是土",
        "short_description": "土不是迟缓，而是把自己重新放回稳定与被承托的状态里。",
        "long_description": "你此刻需要的是边界、稳定与身体层面的落地感。土对应的是承托：不是把自己再逼紧一点，而是重新进入一个可以安心落脚的日常节奏。",
        "primary_symbol_title": "虎眼石吊坠 / 手把件",
        "primary_symbol_description": "有边界、有稳定、有守护感，像一块能让你重新站住的矿石。它不是棕色系商品，而是“承托”的主符号。",
        "ritual_object_title": "麻质坐垫 / 静修垫",
        "ritual_object_description": "把“被托住”从概念变成身体真实能感知到的经验，让稳定先发生在身体上。",
        "ambient_object_title": "粗陶茶杯 / 握持器物",
        "ambient_object_description": "通过握持，把稳定落回日常，把承托变成可以重复进入的微小仪式。",
        "sort_order": 30,
    },
    {
        "code": FiveElementProfile.ElementCode.METAL,
        "name": "金",
        "theme_word": "清明",
        "emotion_title": "你现在更需要的，不是更多信息，而是从混乱里回到清明。",
        "emotion_body": "当思绪太多、噪音太满时，真正稀缺的不是新刺激，而是辨认、删减与重新聚焦。",
        "result_title": "你的主导五行是金",
        "short_description": "金不是变冷，而是把注意力从混乱中重新收回来。",
        "long_description": "你此刻适合的是辨认、整理与决断。金对应的是清明：从过载与分散里，回到一个更有秩序、更能看清重点的状态。",
        "primary_symbol_title": "银发晶吊坠 / 项链",
        "primary_symbol_description": "冷、净、有秩序，像光丝被封存在晶体中。它不是冷感饰品，而是“清明”的主符号。",
        "ritual_object_title": "极简金属钢笔",
        "ritual_object_description": "把辨认与决断落到手上的一个动作里，让想法开始变得有方向。",
        "ambient_object_title": "极简沙漏",
        "ambient_object_description": "让秩序进入时间感，提醒你在节奏里重新聚焦。",
        "sort_order": 40,
    },
    {
        "code": FiveElementProfile.ElementCode.WATER,
        "name": "水",
        "theme_word": "深度",
        "emotion_title": "你现在更需要的，不是更快回应世界，而是退回内在深处。",
        "emotion_body": "当外界太吵，你真正需要的可能不是继续应答，而是回到那个能听见自己低声回应的地方。",
        "result_title": "你的主导五行是水",
        "short_description": "水不是逃离，而是重新回到内在的深度与倾听里。",
        "long_description": "你此刻更适合的是收回、洞察与内在回响。水对应的是深度：从外界的噪音中退一步，回到自己真正的感觉与判断。",
        "primary_symbol_title": "青金石吊坠 / 项链",
        "primary_symbol_description": "像夜海、洞察与低声智慧被封存在石头里。它不是蓝色系商品，而是“深度”的主符号。",
        "ritual_object_title": "行动日志本",
        "ritual_object_description": "让反思、命名与记录成为一条向内的路径，让洞察慢慢显形。",
        "ambient_object_title": "小号颂钵",
        "ambient_object_description": "通过声音把你从外界带回内在回响，让深度先被听见。",
        "sort_order": 50,
    },
]

QUESTION_CONFIGS = [
    {
        "prompt": "当你感觉自己最近有点失去状态时，你最想先做什么？",
        "help_text": "选一个最贴近你当下真实反应的选项。",
        "sort_order": 10,
        "options": [
            {"label": "先写下来，让混乱慢慢长出方向。", "scores": {"wood": 2, "water": 1}, "sort_order": 10},
            {"label": "先让身体暖起来，重新找回感觉。", "scores": {"fire": 2, "earth": 1}, "sort_order": 20},
            {"label": "先坐稳一点，把自己重新放回地面。", "scores": {"earth": 2, "metal": 1}, "sort_order": 30},
            {"label": "先清掉杂音，只保留最重要的事。", "scores": {"metal": 2, "water": 1}, "sort_order": 40},
        ],
    },
    {
        "prompt": "最近你更渴望哪一种支持感？",
        "help_text": "不是理想状态，而是你真的想被怎样对待。",
        "sort_order": 20,
        "options": [
            {"label": "一个允许我慢慢展开的空间。", "scores": {"wood": 2, "earth": 1}, "sort_order": 10},
            {"label": "一种能让我回温的陪伴。", "scores": {"fire": 2, "water": 1}, "sort_order": 20},
            {"label": "一种稳稳托住我的日常秩序。", "scores": {"earth": 2, "metal": 1}, "sort_order": 30},
            {"label": "一个能让我安静向内退回的地方。", "scores": {"water": 2, "metal": 1}, "sort_order": 40},
        ],
    },
    {
        "prompt": "如果今天给自己安排一个小仪式，你更想从哪里开始？",
        "help_text": "选一个你最愿意立刻开始的动作。",
        "sort_order": 30,
        "options": [
            {"label": "开始写几句，看看心里真正想长出的是什么。", "scores": {"wood": 2, "water": 1}, "sort_order": 10},
            {"label": "让气味和温度先回来，让身体先松开。", "scores": {"fire": 2, "earth": 1}, "sort_order": 20},
            {"label": "泡一杯茶，握住一个让人安心的器物。", "scores": {"earth": 2, "water": 1}, "sort_order": 30},
            {"label": "把桌面和思绪都清出来，只留最核心的一件事。", "scores": {"metal": 2, "wood": 1}, "sort_order": 40},
        ],
    },
    {
        "prompt": "你最想被别人怎样理解你现在的状态？",
        "help_text": "选一句最像你心里真实想说的话。",
        "sort_order": 40,
        "options": [
            {"label": "我不是拖延，我是在等待一种自然长出的方向。", "scores": {"wood": 2, "water": 1}, "sort_order": 10},
            {"label": "我不是冷淡，我只是需要慢慢恢复温度。", "scores": {"fire": 2, "earth": 1}, "sort_order": 20},
            {"label": "我不是软弱，我只是很想先被稳稳托住。", "scores": {"earth": 2, "water": 1}, "sort_order": 30},
            {"label": "我不是疏离，我只是需要先回到清明和深处。", "scores": {"metal": 1, "water": 2}, "sort_order": 40},
        ],
    },
    {
        "prompt": "最近最消耗你的，通常是什么？",
        "help_text": "想想让你最容易失去自己节奏的那种累。",
        "sort_order": 50,
        "options": [
            {"label": "看不到方向，感觉很多事都长不出来。", "scores": {"wood": 2, "earth": 1}, "sort_order": 10},
            {"label": "热度被一点点耗光，做什么都不再有感觉。", "scores": {"fire": 2, "water": 1}, "sort_order": 20},
            {"label": "一直在撑，撑到连身体都没有地方放下。", "scores": {"earth": 2, "fire": 1}, "sort_order": 30},
            {"label": "噪音太多，脑子里一直停不下来。", "scores": {"metal": 2, "water": 1}, "sort_order": 40},
        ],
    },
    {
        "prompt": "一个理想空间最先给你的感觉应该是什么？",
        "help_text": "不是风格，而是它让你立刻变成什么状态。",
        "sort_order": 60,
        "options": [
            {"label": "有空气感，像一切都还来得及慢慢展开。", "scores": {"wood": 2, "water": 1}, "sort_order": 10},
            {"label": "有温度，让人想停下来重新活过来。", "scores": {"fire": 2, "earth": 1}, "sort_order": 20},
            {"label": "很稳，像一进来就能把自己放下。", "scores": {"earth": 2, "water": 1}, "sort_order": 30},
            {"label": "很干净，能让我一下子看清自己。", "scores": {"metal": 2, "wood": 1}, "sort_order": 40},
        ],
    },
    {
        "prompt": "做决定的时候，你更依赖哪一种感觉？",
        "help_text": "选你最近更常依赖的判断方式。",
        "sort_order": 70,
        "options": [
            {"label": "哪一个方向更有生长感。", "scores": {"wood": 2, "fire": 1}, "sort_order": 10},
            {"label": "哪一个选项更让我重新有热度。", "scores": {"fire": 2, "wood": 1}, "sort_order": 20},
            {"label": "哪一个选择让我更稳、更能落地。", "scores": {"earth": 2, "metal": 1}, "sort_order": 30},
            {"label": "哪一个判断更清楚、更准确。", "scores": {"metal": 2, "water": 1}, "sort_order": 40},
        ],
    },
    {
        "prompt": "当情绪上来时，你更自然的处理方式是什么？",
        "help_text": "不考虑“应该”，只看你最自然的反应。",
        "sort_order": 80,
        "options": [
            {"label": "先写一写，让感觉自己慢慢长出轮廓。", "scores": {"wood": 2, "water": 1}, "sort_order": 10},
            {"label": "先活动起来，让温度和流动重新回来。", "scores": {"fire": 2, "earth": 1}, "sort_order": 20},
            {"label": "先找一个能坐住、能靠住的地方。", "scores": {"earth": 2, "water": 1}, "sort_order": 30},
            {"label": "先退开一点，理一理到底发生了什么。", "scores": {"metal": 2, "water": 1}, "sort_order": 40},
        ],
    },
    {
        "prompt": "你最想重新找回哪一种生命感？",
        "help_text": "选那个一想到就会轻轻松一口气的状态。",
        "sort_order": 90,
        "options": [
            {"label": "重新开始、重新长出来的感觉。", "scores": {"wood": 2, "fire": 1}, "sort_order": 10},
            {"label": "身体和情绪都慢慢回温的感觉。", "scores": {"fire": 2, "earth": 1}, "sort_order": 20},
            {"label": "被托住、重新站稳的感觉。", "scores": {"earth": 2, "metal": 1}, "sort_order": 30},
            {"label": "安静又深刻，能听见自己内在声音的感觉。", "scores": {"water": 2, "metal": 1}, "sort_order": 40},
        ],
    },
    {
        "prompt": "接下来一段时间，最适合你的节奏更像哪一种？",
        "help_text": "不是效率最高，而是最能照顾你当下状态的节奏。",
        "sort_order": 100,
        "options": [
            {"label": "缓慢展开，但一直向前长。", "scores": {"wood": 2, "earth": 1}, "sort_order": 10},
            {"label": "一点一点回温，重新恢复热度和回应。", "scores": {"fire": 2, "water": 1}, "sort_order": 20},
            {"label": "先稳下来，再慢慢把日常重新扶正。", "scores": {"earth": 2, "metal": 1}, "sort_order": 30},
            {"label": "先安静下来，把重点看清，再往前走。", "scores": {"metal": 2, "water": 1}, "sort_order": 40},
        ],
    },
]

PROFILE_PRODUCT_CONFIGS = {
    "wood": [
        {"role": FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL, "name": "绿幽灵吊坠", "subtitle": "Growth Symbol", "short_description": "木的主符号，像枝叶与雾气被封存在晶体里。", "description": "不是绿色商品，而是重新生长的开始。", "price": "399.00", "sort_order": 10, "blurb": "让生长先被看见。"},
        {"role": FiveElementProfileProduct.ProductRole.RITUAL_OBJECT, "name": "书写本", "subtitle": "Growth Journal", "short_description": "让内在变化被记录、被慢慢展开。", "description": "通过书写，把变化显影出来。", "price": "89.00", "sort_order": 20, "blurb": "把变化写下来，才会慢慢看见自己。"},
        {"role": FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT, "name": "木系精油", "subtitle": "Wood Scent", "short_description": "把木主题延伸到呼吸与空间。", "description": "让生长成为可被闻到的氛围。", "price": "169.00", "sort_order": 30, "blurb": "让空间也和你一起开始生长。"},
    ],
    "fire": [
        {"role": FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL, "name": "石榴石吊坠", "subtitle": "Warmth Symbol", "short_description": "深红与余烬里的热，承接成熟感与生命力。", "description": "不是红色饰品，而是回温的主符号。", "price": "429.00", "sort_order": 10, "blurb": "先把温度带回你身上。"},
        {"role": FiveElementProfileProduct.ProductRole.RITUAL_OBJECT, "name": "肉桂精油", "subtitle": "Warm Spice Oil", "short_description": "把火变成身体可感知的温度。", "description": "从香气开始，找回热度。", "price": "159.00", "sort_order": 20, "blurb": "让回温先发生在呼吸里。"},
        {"role": FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT, "name": "香气仪式扩香木", "subtitle": "Warm Diffuser", "short_description": "让温度从个体延伸到空间。", "description": "让回温成为一个可停留的场。", "price": "129.00", "sort_order": 30, "blurb": "让温度在空间里留下来。"},
    ],
    "earth": [
        {"role": FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL, "name": "虎眼石手把件", "subtitle": "Grounding Symbol", "short_description": "有边界、有稳定、有守护感。", "description": "不是棕色系商品，而是承托的主符号。", "price": "259.00", "sort_order": 10, "blurb": "先让自己重新站稳。"},
        {"role": FiveElementProfileProduct.ProductRole.RITUAL_OBJECT, "name": "麻质静修垫", "subtitle": "Grounding Mat", "short_description": "把被托住变成身体感受。", "description": "让稳定先发生在身体上。", "price": "219.00", "sort_order": 20, "blurb": "把“被托住”从概念变成经验。"},
        {"role": FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT, "name": "粗陶茶杯", "subtitle": "Holding Cup", "short_description": "通过握持进入稳定的日常仪式。", "description": "让承托落进每天都能重复的动作里。", "price": "119.00", "sort_order": 30, "blurb": "从握在手里的稳定开始。"},
    ],
    "metal": [
        {"role": FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL, "name": "银发晶吊坠", "subtitle": "Clarity Symbol", "short_description": "冷、净、有秩序，像光丝封存在晶体里。", "description": "不是冷感饰品，而是清明的主符号。", "price": "459.00", "sort_order": 10, "blurb": "先把注意力收回来。"},
        {"role": FiveElementProfileProduct.ProductRole.RITUAL_OBJECT, "name": "极简金属钢笔", "subtitle": "Clarity Pen", "short_description": "承接秩序、辨认、决断与 intentional thought。", "description": "让清明进入一个可落手的动作。", "price": "239.00", "sort_order": 20, "blurb": "用一个动作，把混乱变得可辨认。"},
        {"role": FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT, "name": "极简沙漏", "subtitle": "Clarity Timer", "short_description": "表达秩序中的时间感。", "description": "让主题从清理走向专注。", "price": "149.00", "sort_order": 30, "blurb": "让节奏替你保留清明。"},
    ],
    "water": [
        {"role": FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL, "name": "青金石吊坠", "subtitle": "Depth Symbol", "short_description": "像夜海、洞察与低声智慧。", "description": "不是蓝色系商品，而是深度的主符号。", "price": "389.00", "sort_order": 10, "blurb": "先回到你自己的低声回应里。"},
        {"role": FiveElementProfileProduct.ProductRole.RITUAL_OBJECT, "name": "行动日志本", "subtitle": "Depth Journal", "short_description": "承接反思、命名、记录与 inner listening。", "description": "把洞察慢慢写出来。", "price": "96.00", "sort_order": 20, "blurb": "让深处的东西有地方被写下来。"},
        {"role": FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT, "name": "小号颂钵", "subtitle": "Depth Bowl", "short_description": "通过声音把人带回内在回响。", "description": "让深度先被听见，再被进入。", "price": "179.00", "sort_order": 30, "blurb": "用声音把自己带回内在。"},
    ],
}


class Command(BaseCommand):
    help = "Seed default five-element quiz content for the XUANOR site."

    def handle(self, *args, **options):
        quiz, _created = FiveElementQuiz.objects.update_or_create(
            slug=QUIZ_CONFIG["slug"],
            defaults=QUIZ_CONFIG,
        )

        profile_map = {}
        for profile_payload in PROFILE_CONFIGS:
            profile, _created = FiveElementProfile.objects.update_or_create(
                quiz=quiz,
                code=profile_payload["code"],
                defaults={**profile_payload, "quiz": quiz, "is_active": True},
            )
            profile_map[profile.code] = profile

        FiveElementQuestion.objects.filter(quiz=quiz).exclude(prompt__in=[item["prompt"] for item in QUESTION_CONFIGS]).delete()
        for question_payload in QUESTION_CONFIGS:
            options_payload = question_payload["options"]
            question_defaults = {key: value for key, value in question_payload.items() if key != "options"}
            question, _created = FiveElementQuestion.objects.update_or_create(
                quiz=quiz,
                prompt=question_payload["prompt"],
                defaults={**question_defaults, "quiz": quiz, "is_active": True},
            )
            existing_labels = [option["label"] for option in options_payload]
            question.options.exclude(label__in=existing_labels).delete()
            for option_payload in options_payload:
                scores_payload = option_payload["scores"]
                option_defaults = {key: value for key, value in option_payload.items() if key != "scores"}
                option, _created = FiveElementOption.objects.update_or_create(
                    question=question,
                    label=option_payload["label"],
                    defaults={**option_defaults, "question": question, "is_active": True},
                )
                FiveElementOptionScore.objects.filter(option=option, profile__quiz=quiz).exclude(profile__code__in=scores_payload.keys()).delete()
                for profile_code, score in scores_payload.items():
                    FiveElementOptionScore.objects.update_or_create(
                        option=option,
                        profile=profile_map[profile_code],
                        defaults={"score": score},
                    )

        category, _created = Category.objects.update_or_create(
            slug="five-element-rituals",
            defaults={
                "name": "五行仪式系统",
                "description": "围绕五行情绪结果组织的主符号、仪式物与氛围/承接物。",
                "is_active": True,
            },
        )

        for profile_code, products in PROFILE_PRODUCT_CONFIGS.items():
            profile = profile_map[profile_code]
            keep_product_ids = []
            for index, product_payload in enumerate(products, start=1):
                slug = f"{profile_code}-{product_payload['role']}-{index}"
                product, _created = Product.objects.update_or_create(
                    slug=slug,
                    defaults={
                        "name": product_payload["name"],
                        "sku": f"XUANOR-{profile_code.upper()}-{index:02d}",
                        "category": category,
                        "subtitle": product_payload["subtitle"],
                        "short_description": product_payload["short_description"],
                        "description": product_payload["description"],
                        "price": product_payload["price"],
                        "currency": Product.Currency.CNY,
                        "stock_quantity": 20,
                        "is_featured": index == 1,
                        "is_active": True,
                        "is_purchasable": True,
                        "sort_order": profile.sort_order + product_payload["sort_order"],
                    },
                )
                keep_product_ids.append(product.id)
                FiveElementProfileProduct.objects.update_or_create(
                    profile=profile,
                    product=product,
                    role=product_payload["role"],
                    defaults={
                        "blurb": product_payload["blurb"],
                        "sort_order": product_payload["sort_order"],
                        "is_active": True,
                    },
                )
            profile.product_mappings.exclude(product_id__in=keep_product_ids).delete()

        self.stdout.write(self.style.SUCCESS(f"Five-element quiz ready: {quiz.title}"))
