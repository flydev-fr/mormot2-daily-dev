#!/usr/bin/env python3
"""Interface strings and the per-language text resolver.

Two separate things live here:

* `STRINGS` — the site's own chrome, which this repository translates: nav,
  column headings, filter labels, severity and category names, the About page.
* `tr()` — the resolver for text the *reviewer* wrote. Those fields arrive from
  `data/analysis/<edition>.json` either as a plain string (English) or as an
  object keyed by language, per `schema/analysis.schema.json`.

English is the fallback for both. A page in another language that shows an
untranslated edition is still useful — the reader gets a translated interface
around English prose — but it must say so, and the prose must carry lang="en"
so a screen reader does not pronounce English with Russian phonetics.
"""

from __future__ import annotations

# Order matters: it is the order of the language switcher, and `en` is first
# because it is canonical and lives at the site root.
LANGS = ["en", "fr", "zh", "ru"]

LANG_NAMES = {
    "en": "English",
    "fr": "Français",
    "zh": "中文",
    "ru": "Русский",
}

# BCP 47 tags for the lang attribute and hreflang.
LANG_TAGS = {"en": "en", "fr": "fr", "zh": "zh-Hans", "ru": "ru"}


def prefix(lang: str) -> str:
    """URL path segment for a language tree. English is the site root."""
    return "" if lang == "en" else f"{lang}/"


def tr(value, lang: str) -> tuple[str, str]:
    """Resolve a reviewer-written field. Returns (text, the language it is in).

    A plain string is English by definition — that is what an edition written
    before translation existed looks like, and the schema still accepts it.
    """
    if isinstance(value, dict):
        text = value.get(lang)
        # A translation identical to the English is not a translation. Treating
        # it as absent lets the page mark the edition untranslated instead of
        # presenting the English as though someone had rendered it.
        if text and text != value.get("en"):
            return text, lang
        return value.get("en", ""), "en"
    return (value or ""), "en"


def tr_list(value, lang: str) -> tuple[list, str]:
    """Same, for `tldr` — a list per language rather than a string."""
    if isinstance(value, dict):
        items = value.get(lang)
        if items and items != value.get("en"):
            return list(items), lang
        return list(value.get("en", []) or []), "en"
    return list(value or []), "en"


def S(lang: str, key: str, **fmt) -> str:
    """An interface string, falling back to English if one is missing."""
    table = STRINGS.get(lang, {})
    text = table.get(key) or STRINGS["en"].get(key, key)
    return text.format(**fmt) if fmt else text


STRINGS: dict[str, dict[str, str]] = {}

STRINGS["en"] = {
    "listen": "Listen",
    "listen_meta": "{mins} min · {mb} MB",
    "listen_in": "in {language}",
    "listen_dl": "download",
    "tagline": "Daily read of upstream commits",
    "skip": "Skip to content",
    "theme_aria": "Switch colour theme",
    "lang_aria": "Language",
    "nav_today": "Today",
    "nav_archive": "Archive",
    "nav_units": "Units",
    "nav_about": "About",
    "nav_upstream": "Upstream",
    "footer_note": "summaries machine-written, commits authoritative",
    "footer_built": "built",
    # masthead
    "tldr": "TL;DR",
    "upgrade_advice": "Upgrade advice",
    "notes_aria": "Notes from the reviewer",
    "fact_build": "Build",
    "fact_commits": "Commits",
    "fact_lines": "Lines",
    "fact_read": "Read",
    "read_min": "{n} min",
    "banner_unreviewed": "Not reviewed yet — entries below are auto-classified "
                         "from commit messages and diffs.",
    "untranslated": "This edition has not been translated yet. The review below "
                    "is shown in English.",
    # risk
    "risk_calm": "Calm",
    "risk_worth-a-look": "Worth a look",
    "risk_act-now": "Act now",
    "why_calm": "internal churn",
    "why_worth-a-look": "a fix or feature you may want",
    "why_act-now": "can affect a running system",
    # toolbar
    "search_placeholder": "Search headline, unit, impact…",
    "search_label": "Search this edition",
    "all_categories": "All categories",
    "all_severities": "All severities",
    "label_category": "Category",
    "label_severity": "Severity",
    "action_needed": "Action needed",
    "reviewed_only": "Reviewed only",
    "stories": "Stories",
    "count_line": "{shown} of {total} entries · {commits} commits upstream",
    # table
    "col_entry": "Entry",
    "col_units": "Units",
    "col_commit": "Commit",
    "sort_by_size": "Sort by the size of the change",
    "no_hits": "Nothing matches those filters.",
    "impact": "Impact",
    "what_changed": "What changed",
    "public_api": "Public API",
    "view_commit": "view the commit on GitHub →",
    "chip_auto": "auto",
    "chip_auto_title": "Classified automatically from the commit message and "
                       "diff — no editorial pass",
    "chip_interp": "interp",
    "chip_interp_title": "The reviewer's reading of the consequences, not "
                         "something the commit states",
    # severity + category + action
    "sev_critical": "Critical", "sev_high": "High",
    "sev_medium": "Medium", "sev_low": "Low",
    "cat_breaking": "Breaking changes", "cat_security": "Security",
    "cat_fix": "Fixes", "cat_feature": "New features",
    "cat_performance": "Performance", "cat_compat": "Compiler & platform",
    "cat_deprecation": "Deprecations", "cat_refactor": "Under the hood",
    "cat_tests": "Tests", "cat_docs": "Docs", "cat_chore": "Housekeeping",
    "act_none": "No action", "act_review": "Worth a look",
    "act_upgrade-recommended": "Upgrade recommended",
    "act_migration-required": "Migration required",
    # activity
    "activity": "Upstream activity",
    "activity_note": "commits per day · last {days} days",
    "activity_aria": "Commits per day over the last {days} days, peak {peak}",
    "stat_commits": "Commits", "stat_active": "Active days",
    "stat_busiest": "Busiest", "stat_peak": "Peak",
    # other pages
    "empty_title": "Nothing shipped",
    "empty_body": "No commits landed upstream in this window.",
    "earlier": "Earlier editions",
    "all_editions": "All editions →",
    "archive_title": "Archive",
    "archive_count": "{n} editions.",
    "th_date": "Date", "th_edition": "Edition",
    "th_commits": "Commits", "th_top_severity": "Top severity",
    "units_title": "Units",
    "units_count": "{n} units tracked.",
    "units_empty": "No unit-level data yet.",
    "about_title": "About",
    "about_pipeline": "Pipeline",
    "about_p1": "A scheduled job pulls new commits of {repo} with their diffs.",
    "about_p2": "A deterministic pass classifies each commit from its message "
                "and files.",
    "about_p3": "A reviewer reads the diffs and writes one JSON file per "
                "edition against a fixed schema.",
    "about_p4": "That JSON is validated — SHAs must resolve, every non-merge "
                "commit covered — before it is merged.",
    "about_p5": "This site is generated from the validated JSON.",
    "about_markers": "Markers",
    "about_m1": "the reviewer's reading, not stated by the commit.",
    "about_m2": "no review pass; classified from the message and diff.",
    "about_m3": "assigned per entry, see the schema.",
    "about_type": "Type",
    "about_type_body": "Two self-hosted faces, no external request. "
                       "{lekton} (ISIA Urbino, OFL) sets everything this "
                       "generator computed; {serrif} sets the titles.",
    "about_lang": "Languages",
    "about_lang_body": "The interface is translated in this repository. The "
                       "review itself is written by the reviewer in each "
                       "language; where a translation is missing, the English "
                       "text is shown and marked as such.",
    "about_feeds": "Feeds",
    "about_feeds_body": "{feed} (RSS) · {data} (every edition and entry, "
                        "machine-readable).",
    "about_caveat": "Summaries are machine-written and can be wrong; the "
                    "commit links are authoritative.",
    "notfound_title": "No edition here",
    "notfound_body": "That page does not exist — or the edition was never "
                     "published.",
    "notfound_page": "Not found",
}

STRINGS["fr"] = {
    "listen": "Écouter",
    "listen_meta": "{mins} min · {mb} Mo",
    "listen_in": "en {language}",
    "listen_dl": "télécharger",
    "tagline": "Lecture quotidienne des commits upstream",
    "skip": "Aller au contenu",
    "theme_aria": "Changer de thème",
    "lang_aria": "Langue",
    "nav_today": "Aujourd’hui",
    "nav_archive": "Archives",
    "nav_units": "Unités",
    "nav_about": "À propos",
    "nav_upstream": "Upstream",
    "footer_note": "résumés écrits par une machine, les commits font foi",
    "footer_built": "généré le",
    "tldr": "En bref",
    "upgrade_advice": "Conseil de mise à jour",
    "notes_aria": "Notes du relecteur",
    "fact_build": "Build",
    "fact_commits": "Commits",
    "fact_lines": "Lignes",
    "fact_read": "Lecture",
    "read_min": "{n} min",
    "banner_unreviewed": "Pas encore relu — les entrées ci-dessous sont "
                         "classées automatiquement à partir des messages de "
                         "commit et des diffs.",
    "untranslated": "Cette édition n’a pas encore été traduite. La revue "
                    "ci-dessous est affichée en anglais.",
    "risk_calm": "Calme",
    "risk_worth-a-look": "À regarder",
    "risk_act-now": "Agir maintenant",
    "why_calm": "remue-ménage interne",
    "why_worth-a-look": "un correctif ou une fonctionnalité utile",
    "why_act-now": "peut affecter un système en production",
    "search_placeholder": "Rechercher titre, unité, impact…",
    "search_label": "Rechercher dans cette édition",
    "all_categories": "Toutes catégories",
    "all_severities": "Toutes sévérités",
    "label_category": "Catégorie",
    "label_severity": "Sévérité",
    "action_needed": "Action requise",
    "reviewed_only": "Relus seulement",
    "stories": "Sujets",
    "count_line": "{shown} sur {total} entrées · {commits} commits upstream",
    "col_entry": "Entrée",
    "col_units": "Unités",
    "col_commit": "Commit",
    "sort_by_size": "Trier par ampleur du changement",
    "no_hits": "Aucun résultat pour ces filtres.",
    "impact": "Impact",
    "what_changed": "Ce qui a changé",
    "public_api": "API publique",
    "view_commit": "voir le commit sur GitHub →",
    "chip_auto": "auto",
    "chip_auto_title": "Classé automatiquement à partir du message de commit "
                       "et du diff — sans relecture éditoriale",
    "chip_interp": "interp.",
    "chip_interp_title": "Interprétation du relecteur, pas une affirmation du "
                         "commit",
    "sev_critical": "Critique", "sev_high": "Élevée",
    "sev_medium": "Moyenne", "sev_low": "Faible",
    "cat_breaking": "Ruptures", "cat_security": "Sécurité",
    "cat_fix": "Correctifs", "cat_feature": "Nouveautés",
    "cat_performance": "Performance", "cat_compat": "Compilateur & plateforme",
    "cat_deprecation": "Obsolescences", "cat_refactor": "Sous le capot",
    "cat_tests": "Tests", "cat_docs": "Documentation",
    "cat_chore": "Entretien",
    "act_none": "Aucune action", "act_review": "À regarder",
    "act_upgrade-recommended": "Mise à jour recommandée",
    "act_migration-required": "Migration nécessaire",
    "activity": "Activité upstream",
    "activity_note": "commits par jour · {days} derniers jours",
    "activity_aria": "Commits par jour sur les {days} derniers jours, pic à "
                     "{peak}",
    "stat_commits": "Commits", "stat_active": "Jours actifs",
    "stat_busiest": "Plus chargé", "stat_peak": "Pic",
    "empty_title": "Rien livré",
    "empty_body": "Aucun commit upstream sur cette période.",
    "earlier": "Éditions précédentes",
    "all_editions": "Toutes les éditions →",
    "archive_title": "Archives",
    "archive_count": "{n} éditions.",
    "th_date": "Date", "th_edition": "Édition",
    "th_commits": "Commits", "th_top_severity": "Sévérité max",
    "units_title": "Unités",
    "units_count": "{n} unités suivies.",
    "units_empty": "Pas encore de données par unité.",
    "about_title": "À propos",
    "about_pipeline": "Chaîne de traitement",
    "about_p1": "Une tâche planifiée récupère les nouveaux commits de {repo} "
                "avec leurs diffs.",
    "about_p2": "Une passe déterministe classe chaque commit d’après son "
                "message et ses fichiers.",
    "about_p3": "Un relecteur lit les diffs et écrit un fichier JSON par "
                "édition, conforme à un schéma fixe.",
    "about_p4": "Ce JSON est validé — chaque SHA doit correspondre, chaque "
                "commit hors fusion être couvert — avant d’être fusionné.",
    "about_p5": "Ce site est généré à partir du JSON validé.",
    "about_markers": "Marqueurs",
    "about_m1": "lecture du relecteur, non affirmée par le commit.",
    "about_m2": "sans relecture ; classé d’après le message et le diff.",
    "about_m3": "attribués par entrée, voir le schéma.",
    "about_type": "Typographie",
    "about_type_body": "Deux polices auto-hébergées, aucune requête externe. "
                       "{lekton} (ISIA Urbino, OFL) compose tout ce que ce "
                       "générateur calcule ; {serrif} compose les titres.",
    "about_lang": "Langues",
    "about_lang_body": "L’interface est traduite dans ce dépôt. La revue "
                       "elle-même est écrite par le relecteur dans chaque "
                       "langue ; à défaut de traduction, le texte anglais est "
                       "affiché et signalé comme tel.",
    "about_feeds": "Flux",
    "about_feeds_body": "{feed} (RSS) · {data} (toutes les éditions et "
                        "entrées, lisible par une machine).",
    "about_caveat": "Les résumés sont écrits par une machine et peuvent se "
                    "tromper ; les liens vers les commits font foi.",
    "notfound_title": "Aucune édition ici",
    "notfound_body": "Cette page n’existe pas — ou l’édition n’a jamais été "
                     "publiée.",
    "notfound_page": "Introuvable",
}

STRINGS["zh"] = {
    "listen": "收听",
    "listen_meta": "{mins} 分钟 · {mb} MB",
    "listen_in": "（{language}）",
    "listen_dl": "下载",
    "tagline": "每日上游提交速读",
    "skip": "跳到正文",
    "theme_aria": "切换配色主题",
    "lang_aria": "语言",
    "nav_today": "今日",
    "nav_archive": "存档",
    "nav_units": "单元",
    "nav_about": "关于",
    "nav_upstream": "上游",
    "footer_note": "摘要由机器撰写，以提交记录为准",
    "footer_built": "构建于",
    "tldr": "要点",
    "upgrade_advice": "升级建议",
    "notes_aria": "审阅者备注",
    "fact_build": "版本号",
    "fact_commits": "提交",
    "fact_lines": "行数",
    "fact_read": "阅读",
    "read_min": "{n} 分钟",
    "banner_unreviewed": "尚未审阅——下方条目由提交信息和差异自动分类。",
    "untranslated": "本期尚未翻译，下方内容以英文显示。",
    "risk_calm": "平静",
    "risk_worth-a-look": "值得一看",
    "risk_act-now": "立即处理",
    "why_calm": "内部改动",
    "why_worth-a-look": "可能需要的修复或功能",
    "why_act-now": "可能影响正在运行的系统",
    "search_placeholder": "搜索标题、单元、影响…",
    "search_label": "在本期中搜索",
    "all_categories": "全部类别",
    "all_severities": "全部严重程度",
    "label_category": "类别",
    "label_severity": "严重程度",
    "action_needed": "需要处理",
    "reviewed_only": "仅已审阅",
    "stories": "主题",
    "count_line": "{total} 条中的 {shown} 条 · 上游 {commits} 次提交",
    "col_entry": "条目",
    "col_units": "单元",
    "col_commit": "提交",
    "sort_by_size": "按改动规模排序",
    "no_hits": "没有符合筛选条件的条目。",
    "impact": "影响",
    "what_changed": "改动内容",
    "public_api": "公开 API",
    "view_commit": "在 GitHub 上查看该提交 →",
    "chip_auto": "自动",
    "chip_auto_title": "根据提交信息和差异自动分类——未经人工审阅",
    "chip_interp": "推断",
    "chip_interp_title": "审阅者对后果的解读，并非提交本身的陈述",
    "sev_critical": "严重", "sev_high": "高",
    "sev_medium": "中", "sev_low": "低",
    "cat_breaking": "破坏性变更", "cat_security": "安全",
    "cat_fix": "修复", "cat_feature": "新功能",
    "cat_performance": "性能", "cat_compat": "编译器与平台",
    "cat_deprecation": "弃用", "cat_refactor": "内部重构",
    "cat_tests": "测试", "cat_docs": "文档", "cat_chore": "杂项",
    "act_none": "无需处理", "act_review": "值得一看",
    "act_upgrade-recommended": "建议升级",
    "act_migration-required": "需要迁移",
    "activity": "上游活动",
    "activity_note": "每日提交数 · 最近 {days} 天",
    "activity_aria": "最近 {days} 天的每日提交数，峰值 {peak}",
    "stat_commits": "提交", "stat_active": "活跃天数",
    "stat_busiest": "最忙一天", "stat_peak": "峰值",
    "empty_title": "本期无提交",
    "empty_body": "此时间段内上游没有提交。",
    "earlier": "往期",
    "all_editions": "全部往期 →",
    "archive_title": "存档",
    "archive_count": "共 {n} 期。",
    "th_date": "日期", "th_edition": "期次",
    "th_commits": "提交", "th_top_severity": "最高严重程度",
    "units_title": "单元",
    "units_count": "已跟踪 {n} 个单元。",
    "units_empty": "暂无单元级数据。",
    "about_title": "关于",
    "about_pipeline": "处理流程",
    "about_p1": "定时任务拉取 {repo} 的新提交及其差异。",
    "about_p2": "一个确定性步骤根据提交信息和文件对每个提交进行分类。",
    "about_p3": "审阅者阅读差异，按固定模式为每期写出一个 JSON 文件。",
    "about_p4": "该 JSON 在合并前会被校验——每个 SHA 必须能对应，"
                "每个非合并提交都必须覆盖。",
    "about_p5": "本站由校验通过的 JSON 生成。",
    "about_markers": "标记说明",
    "about_m1": "审阅者的解读，并非提交本身的陈述。",
    "about_m2": "未经审阅；根据提交信息和差异分类。",
    "about_m3": "逐条标注，详见模式定义。",
    "about_type": "字体",
    "about_type_body": "两款自托管字体，无外部请求。{lekton}（ISIA Urbino，"
                       "OFL）用于本生成器计算出的所有内容；{serrif} 用于标题。",
    "about_lang": "语言",
    "about_lang_body": "界面由本仓库翻译。评述本身由审阅者以各语言撰写；"
                       "缺少翻译时会显示英文原文并加以标注。",
    "about_feeds": "订阅",
    "about_feeds_body": "{feed}（RSS）· {data}（全部期次与条目，机器可读）。",
    "about_caveat": "摘要由机器撰写，可能有误；以提交链接为准。",
    "notfound_title": "此处没有期次",
    "notfound_body": "该页面不存在——或该期从未发布。",
    "notfound_page": "未找到",
}

STRINGS["ru"] = {
    "listen": "Слушать",
    "listen_meta": "{mins} мин · {mb} МБ",
    "listen_in": "на языке: {language}",
    "listen_dl": "скачать",
    "tagline": "Ежедневный обзор коммитов апстрима",
    "skip": "Перейти к содержимому",
    "theme_aria": "Переключить тему",
    "lang_aria": "Язык",
    "nav_today": "Сегодня",
    "nav_archive": "Архив",
    "nav_units": "Модули",
    "nav_about": "О проекте",
    "nav_upstream": "Апстрим",
    "footer_note": "сводки написаны машиной, коммиты — источник истины",
    "footer_built": "собрано",
    "tldr": "Коротко",
    "upgrade_advice": "Рекомендации по обновлению",
    "notes_aria": "Заметки рецензента",
    "fact_build": "Сборка",
    "fact_commits": "Коммиты",
    "fact_lines": "Строки",
    "fact_read": "Чтение",
    "read_min": "{n} мин",
    "banner_unreviewed": "Ещё не отрецензировано — записи ниже "
                         "классифицированы автоматически по сообщениям "
                         "коммитов и диффам.",
    "untranslated": "Этот выпуск ещё не переведён. Обзор ниже показан на "
                    "английском.",
    "risk_calm": "Спокойно",
    "risk_worth-a-look": "Стоит взглянуть",
    "risk_act-now": "Требует действий",
    "why_calm": "внутренние изменения",
    "why_worth-a-look": "исправление или функция, которая может пригодиться",
    "why_act-now": "может затронуть работающую систему",
    "search_placeholder": "Поиск по заголовку, модулю, влиянию…",
    "search_label": "Поиск по этому выпуску",
    "all_categories": "Все категории",
    "all_severities": "Все уровни",
    "label_category": "Категория",
    "label_severity": "Уровень",
    "action_needed": "Нужны действия",
    "reviewed_only": "Только отрецензированные",
    "stories": "Сюжеты",
    "count_line": "{shown} из {total} записей · {commits} коммитов в апстриме",
    "col_entry": "Запись",
    "col_units": "Модули",
    "col_commit": "Коммит",
    "sort_by_size": "Сортировать по объёму изменений",
    "no_hits": "Ничего не найдено по этим фильтрам.",
    "impact": "Влияние",
    "what_changed": "Что изменилось",
    "public_api": "Публичный API",
    "view_commit": "открыть коммит на GitHub →",
    "chip_auto": "авто",
    "chip_auto_title": "Классифицировано автоматически по сообщению коммита "
                       "и диффу — без редакторской проверки",
    "chip_interp": "трактовка",
    "chip_interp_title": "Трактовка последствий рецензентом, а не "
                         "утверждение коммита",
    "sev_critical": "Критический", "sev_high": "Высокий",
    "sev_medium": "Средний", "sev_low": "Низкий",
    "cat_breaking": "Несовместимые изменения", "cat_security": "Безопасность",
    "cat_fix": "Исправления", "cat_feature": "Новые возможности",
    "cat_performance": "Производительность",
    "cat_compat": "Компилятор и платформы",
    "cat_deprecation": "Устаревание", "cat_refactor": "Внутреннее устройство",
    "cat_tests": "Тесты", "cat_docs": "Документация",
    "cat_chore": "Обслуживание",
    "act_none": "Действий не нужно", "act_review": "Стоит взглянуть",
    "act_upgrade-recommended": "Рекомендуется обновиться",
    "act_migration-required": "Требуется миграция",
    "activity": "Активность апстрима",
    "activity_note": "коммитов в день · последние {days} дней",
    "activity_aria": "Коммиты по дням за последние {days} дней, пик {peak}",
    "stat_commits": "Коммиты", "stat_active": "Активных дней",
    "stat_busiest": "Пик активности", "stat_peak": "Максимум",
    "empty_title": "Ничего не выпущено",
    "empty_body": "За этот период в апстриме не было коммитов.",
    "earlier": "Прошлые выпуски",
    "all_editions": "Все выпуски →",
    "archive_title": "Архив",
    "archive_count": "Выпусков: {n}.",
    "th_date": "Дата", "th_edition": "Выпуск",
    "th_commits": "Коммиты", "th_top_severity": "Макс. уровень",
    "units_title": "Модули",
    "units_count": "Отслеживается модулей: {n}.",
    "units_empty": "Пока нет данных по модулям.",
    "about_title": "О проекте",
    "about_pipeline": "Конвейер",
    "about_p1": "Запланированная задача забирает новые коммиты {repo} вместе "
                "с диффами.",
    "about_p2": "Детерминированный проход классифицирует каждый коммит по "
                "его сообщению и файлам.",
    "about_p3": "Рецензент читает диффы и пишет один JSON-файл на выпуск по "
                "фиксированной схеме.",
    "about_p4": "Этот JSON проверяется перед слиянием — каждый SHA должен "
                "разрешаться, каждый неслияниевый коммит быть покрыт.",
    "about_p5": "Сайт генерируется из проверенного JSON.",
    "about_markers": "Пометки",
    "about_m1": "трактовка рецензента, а не утверждение коммита.",
    "about_m2": "без рецензии; классифицировано по сообщению и диффу.",
    "about_m3": "проставляются для каждой записи, см. схему.",
    "about_type": "Шрифты",
    "about_type_body": "Два самостоятельно размещённых шрифта, без внешних "
                       "запросов. {lekton} (ISIA Urbino, OFL) набирает всё, "
                       "что вычислил генератор; {serrif} — заголовки.",
    "about_lang": "Языки",
    "about_lang_body": "Интерфейс переведён в этом репозитории. Сам обзор "
                       "пишет рецензент на каждом языке; если перевода нет, "
                       "показывается английский текст с соответствующей "
                       "пометкой.",
    "about_feeds": "Ленты",
    "about_feeds_body": "{feed} (RSS) · {data} (все выпуски и записи, в "
                        "машиночитаемом виде).",
    "about_caveat": "Сводки написаны машиной и могут ошибаться; источник "
                    "истины — ссылки на коммиты.",
    "notfound_title": "Здесь нет выпуска",
    "notfound_body": "Такой страницы не существует — или выпуск никогда не "
                     "публиковался.",
    "notfound_page": "Не найдено",
}


def missing_keys() -> dict[str, list[str]]:
    """Keys present in English but absent from another language."""
    base = set(STRINGS["en"])
    return {l: sorted(base - set(STRINGS[l])) for l in LANGS if l != "en"}


# Dates are formatted here rather than with strftime: %A/%B follow the build
# machine's locale, which on CI is English regardless of the page language.
MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"],
    "zh": ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月",
           "10月", "11月", "12月"],
    "ru": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"],
}

WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
           "Sunday"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
           "dimanche"],
    "zh": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
    "ru": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота",
           "воскресенье"],
}


def long_date(day, lang: str) -> str:
    """A date.date as a reader-facing string in `lang`."""
    wd = WEEKDAYS.get(lang, WEEKDAYS["en"])[day.weekday()]
    mo = MONTHS.get(lang, MONTHS["en"])[day.month - 1]
    if lang == "zh":
        return f"{day.year}年{day.month}月{day.day}日 {wd}"
    if lang == "ru":
        return f"{wd}, {day.day} {mo} {day.year}"
    if lang == "fr":
        return f"{wd} {day.day} {mo} {day.year}"
    return f"{wd} {day.day:02d} {mo} {day.year}"
