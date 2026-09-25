import ast
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from comic_checker import wikipedia_client
from comic_checker.wikipedia_client import (
    ADOPTION_PATH_DIRECT_DISAMBIGUATION,
    ADOPTION_PATH_DIRECT_PLAIN,
    ADOPTION_PATH_SEARCH_EXACT,
    ADOPTION_PATH_SEARCH_SUBTITLE,
    API_MAX_ATTEMPTS,
    API_REQUEST_INTERVAL,
    API_RETRY_BACKOFF_SECONDS,
    COMPLETED_STRONG_RE,
    COMPLETED_WEAK_RE,
    MARKER_MAX_DISTANCE,
    MIGRATION_SAME_SENTENCE_RE,
    ONGOING_RE,
    _accept_article,
    _api_get,
    MANGA_INFOBOX_MARKER,
    STATUS_NOT_FOUND,
    STATUS_UNKNOWN,
    USER_AGENT,
    WikipediaJudgment,
    _declares_merged_coverage,
    _extract_braced_blocks,
    _fetch_extract,
    _fetch_wikitext,
    _has_continuation_evidence,
    _has_ongoing_signal,
    _is_about_manga,
    _is_novel_primary,
    _is_person_article,
    _judge_extract,
    _judge_via_infobox,
    _lands_on_a_different_work,
    _lead_and_first_section,
    _mentions_as_derivative_work,
    _pick_article,
    _pick_via_direct_lookup,
    _pick_via_search,
    _resolve_titles,
    _search_queries,
    _strip_annotations,
    _strip_disambiguation_suffix,
    _strip_trailing_note,
    _title_variants,
    _MAX_REDIRECT_HOPS,
    judge,
)

ONE_PIECE_EXTRACT = (
    "『ONE PIECE』（ワンピース）は、尾田栄一郎による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社）にて1997年34号から連載中。"
)

SHINGEKI_EXTRACT = (
    # 実際のWikipedia記事の冒頭文は、漫画が原作でアニメ化・小説化もされていることを
    # 列挙する形式（「…日本の漫画、およびそれを原作としたアニメ、小説（ライトノベル）、
    # ゲーム、映画などの派生作品。」）になっている。一次分類はあくまで「漫画」であり、
    # 派生作品としての「小説」の語が出現するだけで判定不能に倒れてはならない。
    "『進撃の巨人』は、諫山創による日本の漫画、およびそれを原作としたアニメ、"
    "小説（ライトノベル）、ゲームなどの派生作品。"
    "『別冊少年マガジン』（講談社）にて2021年4月9日発売の5月号をもって完結した。"
)

DANDADAN_EXTRACT = (
    "『ダンダダン』は、龍幸伸による日本の漫画作品。"
    "『少年ジャンプ+』（集英社）にて2021年4月6日から連載中。"
)

AO_NO_HAKO_EXTRACT = (
    "『アオのハコ』は、三浦糀による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社）にて2021年19号から2026年33号まで連載された。"
)

TENSURA_EXTRACT = (
    "『転生したらスライムだった件』は、伏瀬による日本のライトノベル、およびそれを"
    "原作とするメディアミックス作品。"
    "原作のライトノベルは全21巻で完結した。"
    "川上泰樹による漫画版は『月刊少年シリウス』（講談社）にて連載中で、32巻まで刊行されている。"
)

TENSURA_NO_MANGA_SENTENCE_EXTRACT = (
    "『例のラノベ』は、某作者による日本のライトノベル、およびそれを原作とする"
    "メディアミックス作品。"
    "原作のライトノベルは全10巻で完結した。"
    "コミカライズも展開されている。"
)

# 実際の記事から取得した文言（休載節）そのまま。「週刊連載を終了」という語だけを見ると
# COMPLETED_WEAK_REにマッチするが、文の後半で「継続」を発表しており、作品自体は
# 終わっていない（連載頻度・掲載形態が変わっただけ）。誤って「完結」と判定していた
# 実際のバグの回帰テスト。
HUNTER_HUNTER_EXTRACT = (
    "『HUNTER×HUNTER』（ハンター×ハンター）は、冨樫義博による日本の漫画。"
    "『週刊少年ジャンプ』にて1998年14号より連載を開始。"
    "同年12月26日発売の2023年4・5合併号の第400話を最後に週刊連載を終了し、"
    "第401話以降は冨樫の体調を考慮して「週刊連載ではない掲載形態での継続」を発表した。"
)

# M6-D-1（Issue #11）の実データ調査で確認したケース。「連載されている」という、既存の
# フィクスチャ（「連載中」）とは異なる現在形の表現で連載中と判定できることを確認する。
JOJO_EXTRACT = (
    "『ジョジョの奇妙な冒険』は、荒木飛呂彦による日本の漫画作品。"
    "集英社の『週刊少年ジャンプ』に1986年から2004年まで、2005年からは『ウルトラジャンプ』"
    "に長期にわたって連載されている。"
)

# M6-D-1で確認したケース。作者急逝後も連載が続いているという実世界の事例で、通常の
# 「連載中」判定がそのまま機能することの確認（regexの挙動としては目新しくないが、
# 実際に確認した著名な事例として固定しておく）。
BERSERK_EXTRACT = (
    "『ベルセルク』は、三浦建太郎による日本の漫画作品。"
    "白泉社発行の漫画誌『ヤングアニマル』にて連載中。"
)

# M6-D-1で確認したケース。「まで連載され、その後も約年1回のペースで新作が作られている」
# という文言は、HUNTER×HUNTERと表面的には似た構造（週刊連載終了+その後の展開への言及）
# だが、意図的にCONTINUATION_VETO_REの対象にしていない。週刊連載という一つの物語は
# 完結しており、その後の新作は不定期のアニバーサリー的な追加作品という性質の違いが
# あるため（詳細はCLAUDE.md参照）。この判断そのものが変わらないことを保証する回帰テスト。
# M6-D-2（Issue #35）の実測で判明したとおり、実際の記事にはこのあとに「単行本は連載中は
# 全200巻…」という文が続く。Issue #36の修正前は、この「連載中は」がONGOING_REに誤爆して
# _has_ongoing_signal()を真にし、正しい根拠である「まで連載され…」の弱シグナルを抑止して
# いた（その結果、走査が進んで無関係な「基本的に一話完結だが」が根拠に採用されていた。
# 「一話完結」の誤爆自体はIssue #37で別途対応する）。当初のフィクスチャはこの文を含んで
# いなかったため、既存テストはこのバグを検出できていなかった。
KOCHIKAME_EXTRACT = (
    "『こちら葛飾区亀有公園前派出所』は、秋本治による日本の漫画作品。"
    "『週刊少年ジャンプ』において1976年42号から2016年42号まで連載され、"
    "その後も約年1回のペースで新作が作られている。"
    "単行本は連載中は全200巻、2021年に連載終了後に新たに描かれたエピソードを集めた"
    "201巻（2026年現在最新刊）が刊行され、これは2021年に『ゴルゴ13』に抜かれるまでは"
    "「最も発行巻数が多い単一漫画シリーズ」としてギネス世界記録に認定されていた。"
)

# Issue #36: 実際の『大奥 (漫画)』のリード文そのまま。「連載中から」は受賞したのが連載期間中
# だったことを述べる修飾語で、現在の連載状況ではない。修正前はこれがONGOING_REに一致して
# 正しい完結文（2文目）を抑止したうえ、この文自身が採用されて「連載中」と誤答していた。
# M6-D-2で観測された唯一の「誤った断定」であり、本Issueを最優先とした理由そのもの。
OOOKU_EXTRACT = (
    "『大奥』（おおおく）は、よしながふみによる日本のフィクション・時代物の少女漫画。"
    "隔月刊誌『MELODY』（白泉社）にて2004年8月号から2021年2月号まで連載された。"
    "連載中から多くの日本の漫画賞（#受賞歴）を受賞し、ジェンダーに対する理解を深める"
    "内容を称えられジェイムズ・ティプトリー・ジュニア賞も受賞・国内外での評価は高い。"
)

# Issue #36: 実際の『鋼の錬金術師』の記事から、リード文と走査範囲内の該当文を抜粋。
# 「連載中作品」は同誌に載っている*他作品*を指しており、本作の状況ではない。修正前は
# これがONGOING_REに一致して正しい完結文を抑止し、かつこの文自身は連載中と完結の両方の
# シグナルを持つため採用もされず、判定不能に落ちていた（偽陰性）。
HAGANE_NO_RENKINJUTSUSHI_EXTRACT = (
    "『鋼の錬金術師』（はがねのれんきんじゅつし、英題：FULLMETAL ALCHEMIST）は、"
    "荒川弘による日本の漫画、およびそれを原作とした派生作品。"
    "『月刊少年ガンガン』（スクウェア・エニックス）において、2001年8月号から"
    "2010年7月号まで連載された。"
    "また、連載終了時点で『月刊少年ガンガン』の連載中作品の中では、最長連載された作品である。"
)

# Issue #36: 実際の漫画家記事『小田扉』から抜粋。M6-D-2では「こさめちゃん」「横須賀こずえ」
# の2件がこの作者記事にリダイレクトで着地し、最後の文（作者の居住地の説明）を根拠に
# 「連載中」と誤答していた。「連載中の2016年」は時期を指す修飾語である。
#
# 【このフィクスチャで検証しないこと】この2件は、Issue #36を修正しても行としては誤答の
# ままである。抑止が消えた結果、今度は『横須賀こずえ』の連載開始を述べる文（「連載終了と
# 同じ2019年、…」）が採用されて「完結」になるだけで、誤りの中身が変わるにすぎない。
# 根本原因は作者記事に着地する記事選定側にあり、本Issueのスコープ外なので、
# ここではステータスを固定せず「居住地の文が連載シグナルとして扱われないこと」だけを見る。
# 同様に、M6-D-2でカテゴリ2の誤答を出した『業田良家』『押切蓮介』の計5件も本Issueでは
# 直らない。あちらの「（2015年現在も連載中）」は述語位置の正しい用法であり、問題は主語が
# 別作品であること（＝記事選定）だからである。
AUTHOR_ARTICLE_RESIDENCE_EXTRACT = (
    "小田 扉（おだ とびら、1974年 - ）は、日本の漫画家。"
    "連載終了と同じ2019年、『週刊ビッグコミックスピリッツ』にて横須賀市を舞台に据えた"
    "『横須賀こずえ』を連載開始。"
    "『団地ともお』連載中の2016年（平成28年）より神奈川県横須賀市在住。"
)

# M6-D-1で確認したケース。「第一部」「第二部」という語は掲載号の内訳表記であり、
# シリーズの一部だけの完結（M6-B-2で懸念されたパターン）ではない。将来M6-B-2に
# 対応する際、この正当な完結判定を壊さないことを保証する回帰テスト。
DEATH_NOTE_EXTRACT = (
    "『DEATH NOTE』は、大場つぐみ・小畑健による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社、第一部：2004年1号 - 2005年11号、"
    "第二部：2005年20号 - 2006年24号）において、2003年12月から2006年5月まで連載された。"
)

# M6-B-1: 実際の記事（「ゴタ消し -示談交渉人 白井虎次郎-」）から取得した文言そのまま。
# 「打ち切り」を完結として扱う仕様の回帰テスト。判定根拠に「打ち切り」だった事実が
# そのまま残ることも確認する（新ステータスは追加しない仕様のため）。
GOTAKESHI_EXTRACT = (
    "『ゴタ消し -示談交渉人 白井虎次郎-』は、真鍋昌平による日本の漫画作品。"
    "2011年21・22合併号での同誌の休刊をもって連載は打ち切りとなった。"
)

# M6-B-1: 「打ち切りの危機に瀕したが連載は継続した」のような、打ち切られなかった文脈の
# 回帰テスト。COMPLETED_WEAK_REの「打ち切り」は、同一文に継続を示す語（継続/再開/
# 引き続き等）があれば無効化される（Issue #8の設計指針をそのまま適用）。
# 意図的に他の連載中/完結シグナルを含めていない（無効化が効かなくても別の文で
# たまたま正しい結果になる、という誤ったテストにならないようにするため）。
NEAR_CANCELLATION_EXTRACT = (
    "『例の作品』は、某作者による日本の漫画作品。"
    "人気低迷により打ち切りの危機に瀕したが、読者アンケートの巻き返しにより連載は継続した。"
)

# 幽☆遊★白書のケース: COMPLETED_WEAK_RE（「まで連載された」）が実際に完結を意味する
# 場合は、継続を示す語が無ければ従来通り完結と判定できることの確認（HUNTER×HUNTERの
# 修正が過剰に厳格化していないことの回帰テスト）。
YU_YU_HAKUSHO_EXTRACT = (
    "『幽☆遊☆白書』は、冨樫義博による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社）にて、1990年51号から1994年32号にかけて連載された。"
)

# Issue #13の実データ調査で確認したケース（is_multimedia=False、実際のWikipedia記事の
# 冒頭文+「概要」節そのまま）。本編自身の完結文「2017年3月23日まで毎週木曜更新で連載。」
# は「まで」と「連載」の間に語が挟まるため、当時のCOMPLETED_WEAK_REでは取りこぼされて
# いた。その結果、本来は対象外のはずの番外編の連載終了文「番外編「とんかつDJアゲ太郎
# B面〜ファッショニスタへの道〜」が本編と並行で連載された。」が代わりに本編の判定文として
# 採用されてしまっていた（is_multimedia=False経路はMANGA_MARKERS等の主語チェックを
# 行わないため）。この回では本編・番外編どちらも完結済みだったため結果的にステータス自体は
# 正しかったが、両者の連載状況が食い違う作品では誤ったステータスを確信を持って返しうる、
# 実在する不具合だった。SPINOFF_MARKERSによる除外と、「まで...連載」の間隔緩和の
# 両方を確認する回帰テスト。
TONKATSU_DJ_AGETARO_EXTRACT = (
    "『とんかつDJアゲ太郎』（とんかつディージェイアゲたろう）は、イーピャオと"
    "小山ゆうじろうによる日本の漫画。\n\n\n"
    "== 概要 ==\n"
    "とんかつ屋の跡取り息子揚太郎がクラブカルチャーに衝撃を受け、とんかつ屋とDJに"
    "数多くの共通点を見出しながら、その両方を目指して奮闘するギャグ漫画。"
    "『少年ジャンプ+』（以下『J+』、集英社）2014年9月22日より2017年3月23日まで"
    "毎週木曜更新で連載。\n"
    "『J+』創刊作品の一つであり、『J+』から最初に単行本化された作品の一つでもある。"
    "『カラダ探し』などと並び初期『J+』を彩り、2016年には『J+』作品初となる"
    "テレビアニメが放送された。2020年10月30日には実写映画が公開された。\n"
    "制作においては、各話のタイトル・人物名は原案担当のイーピャオが考え、それに"
    "漫画担当の小山がセリフを肉付けしていくという形が採られている。画やセリフなどは"
    "ウェブコミックとしての読みやすさを重視して描かれている。単行本ではDJのYummyが"
    "クラブカルチャーについて解説している。\n"
    "『MEN'S NON-NO』（集英社）2015年1月号から12月号まで、番外編"
    "「とんかつDJアゲ太郎 B面〜ファッショニスタへの道〜」が本編と並行で連載された。"
    "また、『週刊少年ジャンプ』（集英社）2015年4・5合併号と12号に出張読切が"
    "掲載された。\n\n\n"
)

# Issue #38: 実際の『日常』の記事から抜粋。COMPLETED_WEAK_REの「まで...連載」は、
# 「まで」と「連載」の間に語が挟まる言い回し（TONKATSU_DJ_AGETARO_EXTRACT参照）に対応する
# ため間隔を20文字まで許容していたが、「10月まで読み切りを掲載したのち、同年11月から
# 連載に移行。」のように読点をまたいで20文字以内に収まる場合、前半（読み切り掲載の終了）
# と後半（連載の*開始*）という別々の節を一つに束ねて誤爆していた。この文は連載の開始を
# 述べており、完結とは正反対の内容。読点をまたぐ場合を除外して回避する
# （動機だったとんかつDJアゲ太郎の「まで毎週木曜更新で連載。」は読点をまたがないため、
# 引き続き完結と判定できることをtest_tonkatsu_dj_agetaro_main_completion_not_confused_with_spinoffで
# 確認済み）。
#
# さらに次の文には継続を示す語（「再開」）があるが、CONTINUATION_VETO_REは同一文内しか
# 見ないため前の文には効かず、ONGOING_RE（「連載中」「連載されている」）にも一致しない
# ため、M6-B-3のhas_ongoing_elsewhereによる抑止も発火しない。このケースでは
# 「まで...連載」自体を誤爆させないことが直接の対処になる。
NICHIJOU_EXTRACT = (
    "『日常』（にちじょう）は、あらゐけいいちによる日本の漫画作品。"
    "『月刊少年エース』（KADOKAWA（旧角川書店）において2006年5月から10月まで"
    "読み切りを掲載したのち、同年11月から連載に移行。"
    "2015年12月号を最後に連載を一旦終了するも、2021年12月号から再開したが、"
    "2025年2月号から多忙によるスケジュール調整により長期休載となっている。"
)

# 合成フィクスチャ（実データでは未発見）。本編は連載中、番外編は完結済みという、
# TONKATSU_DJ_AGETARO_EXTRACTとは逆に食い違うパターン。番外編の完結文を本編より先に
# 配置し、番外編の文につられて誤った「完結」を返さないこと（スキップされ、本編自身の
# 「連載中」文まで走査が続くこと）を確認する。
SPINOFF_COMPLETED_MAIN_ONGOING_EXTRACT = (
    "『例の連載作品』は、某作者による日本の漫画。"
    "番外編「例の連載作品外伝」は2021年に連載された。"
    "『週刊少年サンプル』（サンプル社）にて2020年から連載中。"
)

# M6-B-3対応の合成フィクスチャ。掲載誌の移籍を2文に分けて書くパターンで、前半の文だけを
# 見ると完結（COMPLETED_WEAK_REの「まで連載」）、後半の文を読むと連載中になる。
# CONTINUATION_VETO_REは同一文内しか見ないため、この形は文をまたいで誤爆していた。
# 実データ由来ではなく合成だが、元になった実例は「一緒に暮らしていいですか?」の
# 「『グランドジャンプむちゃ』にて、2023年3月号から2023年11月号まで連載。その後
# 『グランドジャンプ』（同）に移籍し、2023年23号から連載されている。」である
# （実データそのままではなく、掲載誌名等を伏せた同じ構造の合成に置き換えている）。
MAGAZINE_TRANSFER_ONGOING_EXTRACT = (
    "『例の移籍作品』は、某作者による日本の漫画作品。"
    "『月刊サンプルA』（サンプル社）にて、2023年3月号から2023年11月号まで連載。"
    "その後『週刊サンプルB』（同）に移籍し、2023年23号から連載されている。"
)

# Issue #144（作業92のjudge()実測で発見）、実際のWikipedia記事『セトギワ花ヨメ』の
# リード文そのまま（is_multimedia=False経路）。「次世代編」がSPINOFF_MARKERSに無かった
# ため、本編の子ども世代を主役とする次世代編『仕上げ男子のクロモジ』の連載開始文が
# 本編の判定として誤採用され、「連載中」と誤答していた。
SETOGIWA_HANAYOME_EXTRACT = (
    "『セトギワ花ヨメ』（セトギワはなヨメ）は胡桃ちのによる日本の4コマ漫画作品。"
    "4コマ漫画専門誌『まんがライフオリジナル』（竹書房）にて、2005年6月号より"
    "2023年8月号まで連載。本作の主人公の夫婦の子ども・クロモジを主役として描いた"
    "次世代編の『仕上げ男子のクロモジ』が同誌2024年3月号より3か月連続で掲載された後、"
    "同年8月号から連載されている。"
)

# Issue #144（作業92のjudge()実測で発見）、実際のWikipedia記事『最弱テイマーはゴミ拾いの
# 旅を始めました。』のリード文そのまま（原作ライトノベルのメディアミックス作品で
# is_multimedia=True経路）。SPINOFF_MARKERSチェックがis_multimedia=True経路では
# 実行されない構造だったため、コミカライズのスピンオフ漫画の連載文（「スピンオフ」を
# 含み文字通りSPINOFF_MARKERSにヒットするはずの文）がそのまま本編の判定として
# 誤採用され、「完結」と誤答していた（期待値は「連載中」——コミカライズ本編が
# 新サイトへ移行し最新話はそちらで掲載されている、という記述のため）。
SAIJAKU_TEIMAA_EXTRACT = (
    "『最弱テイマーはゴミ拾いの旅を始めました。』（さいじゃくテイマーはゴミひろいの"
    "たびをはじめました）は、ほのぼのる500による日本のライトノベル。"
    "メディアミックスとして、蕗野冬によるコミカライズがウェブコミック配信サイト"
    "『COMICコロナ』（TOブックス）にて、2020年2月から連載されていたが、"
    "同社が新たにウェブコミック配信サイト『コロナEX』を開設し最新話はそちらで"
    "掲載するようになった。2022年11月からはスピンオフ漫画『私立オードグズ学園中等部！"
    "〜異の国（？）でもやっぱりゴミ拾いしてました〜』も同サイトにて連載された。"
)

# M6-B-3対応の合成フィクスチャ。本編の文が連載中と完結の両シグナルを含んで曖昧扱いで
# スキップされたあと、*別作品*の連載終了に言及した文を掴んでしまうパターン。
# 元になった実例は「サタノファニ」で、本編の「2017年15号から2023年34号まで連載され、
# その後『ヤンマガWeb』に移籍し、同年9月6日より連載中。」がスキップされた結果、
# 概要節の「作者が…『DEATHTOPIA』の連載終了から4か月後に…」を採用していた。
# 別作品名を主語にした文はSPINOFF_MARKERSでは弾けない（番外編でも外伝でもない）ため、
# 走査範囲全体の継続シグナルによる無効化でしか止められない。
# なお、このケースで期待するのは「連載中」ではなく「判定不能」である。本編の文が
# 曖昧である事実は変わらず、fail-closedに倒すのが正しい（Issue #8以来の方針）。
# 本編の文は、Issue #134のMIGRATION_SAME_SENTENCE_RE（「のち／その後／後」を挟む
# 移籍構文）には一致しない形にしてある（「のち」「その後」「後」のいずれも使わない）。
# これらの接続語を使うと本編の文自体がIssue #134により連載中と決着してしまい、
# このテストが検証したい「別作品の文を代用してはならない」という論点を検査できなく
# なるため。
OTHER_WORK_COMPLETION_EXTRACT = (
    "『例の曖昧作品』は、某作者による日本の漫画作品。"
    "『週刊サンプルA』（サンプル社）にて、2017年15号から2023年34号まで連載され、"
    "『サンプルWeb』でも同年9月6日より連載中。"
    "作者が『サンプルB』（サンプル社）で連載していた『別の過去作』の連載終了から"
    "4か月後に『週刊サンプルA』へ移籍し、連載が開始された。"
)

# Issue #134: MIGRATION_SAME_SENTENCE_REの設計根拠そのもの（作業84-3で事前登録した
# 実データ2件）。デュエル・マスターズ（作業83-4で見つけたホールドアウト）はこの設計に
# 一切使っていない。
BURESU_MIGRATION_EXTRACT = (
    "『ブレス』は、園山ゆきのによる日本の漫画作品。"
    "講談社が刊行する『少年マガジンエッジ』にて2022年2月号から2023年11月号まで"
    "連載されたのち、『月刊少年シリウス』に移籍し2024年2月号より連載中。"
)

BLONDIE_MIGRATION_EXTRACT = (
    "『ブロンディ』は、アメリカ合衆国の新聞連載漫画。"
    "新聞連載終了後は文藝春秋『漫画讀本』で連載されている。"
)

# 接続語（のち／その後／後）が無い場合は、従来どおり同一文内競合としてスキップされ
# 判定不能のままであることの確認用（ミューテーション検証で、接続語の要求を外す変異を
# 検出するための陰性対照）。
NO_CONNECTOR_MIGRATION_EXTRACT = (
    "『例の検証作品』は、某作者による日本の漫画作品。"
    "『週刊サンプルX』にて2017年から2023年まで連載され、『サンプルWebY』でも連載中。"
)

# Issue #135（テーマB、作業87-2の設計根拠そのもの、実データ）: 携帯コミック配信
# サイトでの完結を「配信された」（過去形）で捕捉する。
HAISHIN_SARETA_EXTRACT = (
    "『17歳』（じゅうななさい、SEVENTEEN）は、清水洋三による日本の漫画作品。"
    "『モバMAN』（小学館の携帯コミック配信サイト）において2009年1月2日より"
    "2011年3月4日まで配信された。全15話。単行本全2巻。"
)

# 現在形「配信されている」は継続中の配信を意味しうるため、意図的に含めていない
# （作業86-3で実測した誤検知リスク: サイファー「…で配信されている。」、エイケン
# 「…ストリーミング配信のTubiサービスに追加され…」）。ミューテーション検証の陰性
# 対照として、「配信された」と「配信されている」を区別できているかを確認する。
HAISHIN_SARETEIRU_EXTRACT = (
    "『例の配信作品』は、某作者による日本の漫画作品。"
    "『例のサイト』にて2007年から配信されている。"
)

# Issue #37: 実際の『絶体絶命でんぢゃらすじーさん』の記事から、リード文と「概要」節の
# 該当文を抜粋。Issueが「連載中の一話完結型作品を入力した場合、確実に完結と誤答する」と
# 予測したとおりの誤答が、実在の作品で起きていた唯一の事例である（修正前は「基本的には
# 一話完結型のストーリー。」を根拠に`完結`。正しくは末尾の「2025年12月号から連載中。」に
# 基づく`連載中`）。
#
# タイトルを変えながら続くシリーズなので「まで連載された」文が複数あるが、それらは
# M6-B-3の走査範囲全体の継続シグナルによって正しく抑止される。抑止をすり抜けるのは
# 強シグナル扱いだった「一話完結型」だけであり、そこがこのIssueの争点そのものである。
DENJARASU_JIISAN_EXTRACT = (
    "『絶体絶命でんぢゃらすじーさん』（ぜったいぜつめいでんぢゃらすじーさん）は、"
    "曽山一寿による日本の漫画作品。"
    "2001年10月号から『月刊コロコロコミック』にて連載開始し、2010年4月号から"
    "『でんぢゃらすじーさん邪』、2017年4月号から『なんと！でんぢゃらすじーさん』となり、"
    "2025年12月号からは『でんぢゃらすじーさん』とタイトルを変更しながら連載された。\n\n\n"
    "== 概要 ==\n"
    "じーさんと孫が織りなす不条理ギャグコメディで基本的には一話完結型のストーリー。\n"
    "『絶体絶命でんぢゃらすじーさん』は2001年度から2009年度まで連載された。\n"
    "『でんぢゃらすじーさん邪』（でんぢゃらすじーさんじゃ）は2010年度から2016年度まで"
    "連載された。\n"
    "『なんと!でんぢゃらすじーさん』は2017年度から2025年10月号まで連載された。\n"
    "『でんぢゃらすじーさん』は2025年12月号から連載中。"
)

# Issue #37: 実際の『ARIA (漫画)』の記事から、リード文と該当節の文を抜粋。
# このフィクスチャは*2つの誤爆の組み合わせ*を固定する回帰テストである。
#   1. 「1話完結形式で月刊誌に連載された。」… 修正前はここが強シグナルとして決着していた
#      （結果の`完結`は正しいが、根拠として採用される理由が誤っていた）
#   2. 「連載中にエニックスお家騒動が起こり」… ONGOING_REの非述語用法（Issue #36と同クラス）
# 1.の誤爆を止めただけだと、それまで隠れていた2.が露出して`完結`→`連載中`に転ぶ。
# ONGOING_REから「連載中に」を除外する変更を同じ修正に含めているのはこのためであり、
# 片方だけを入れるとこのテストが落ちる。
ARIA_EXTRACT = (
    "『AQUA』（アクア）および『ARIA』（アリア）は、天野こずえによる日本の漫画。"
    "2001年から2008年にかけて、1話完結形式で月刊誌に連載された。\n\n\n"
    "== 作品解説 ==\n"
    "緩やかな季節、時間の流れこそあるものの、基本的に1話完結型である。\n"
    "『AQUA』（アクア）は、『月刊ステンシル』2001年3月号から同年11月号まで連載された"
    "漫画作品。"
    "連載中にエニックスお家騒動が起こり、『月刊コミックブレイド』への移籍にあたって"
    "改題した。"
)

# Issue #37: 実際の『アウターゾーン』の記事から抜粋。「完結」を含む語が2種類、いずれも
# 各話が独立して終わる作品形式の説明として出てくる（「各話完結」と、語順が逆の
# 「完結する回」）。ステータス自体は結果的に`完結`で正しかったが、修正前はこの作風の
# 説明文が判定根拠の列に入っていた。こち亀と同じ「ステータスは偶然正しいが根拠文が
# 連載状況の文ですらない」パターンである。
OUTER_ZONE_EXTRACT = (
    "『アウターゾーン』 (THE OUTER ZONE) は、光原伸による日本の漫画作品。\n"
    "『週刊少年ジャンプ』（集英社）にて1991年14号より連載が開始され、同年24号までの"
    "全10話で一旦終了。"
    "同年51号より第2部として再開し、1994年15号まで連載された。\n\n\n"
    "== 概要 ==\n"
    "本作の原点であるSFテレビドラマ『トワイライト・ゾーン』と同様に基本的には各話完結で"
    "あり、ホラーやオカルトを主な題材としている。"
    "ほとんどの回は現代の日本を舞台としているが、それ以外の国や時代が描かれる場合もあり、"
    "それらの世界の中だけで完結する回もあれば、主人公がそうした異世界に迷い込む回もある。"
    "連載終了後に発表されたシリーズ作品は、『月刊少年ジャンプ』1995年1月号掲載の"
    "読切短編「アウターゾーン スペシャル」がある。"
)

# Issue #37: 実際の漫画家記事『吾妻ひでお』から抜粋。Excelの`リングサイドクレイジー`の行が
# この作者記事に着地し、「1コマを1コママンガとして完結させる」という*作風*の説明文を
# 根拠に`完結`と誤答していた（Issue本文の「実際に誤答した事例」そのもの）。
#
# 【このフィクスチャで検証しないこと】AUTHOR_ARTICLE_RESIDENCE_EXTRACT（Issue #36）と
# まったく同じ理由で、この行は本Issueを修正しても`完結`のままである。使役形の誤爆が
# 消えると、今度は*別作品*（『ざ・色っぷる』）の連載終了文が採用されるだけで、誤りの
# 中身が変わるにすぎない。根本原因は作者記事に着地する記事選定側にあり、本Issueの
# スコープ外（別Issueとして起票予定）。そのためステータスは固定せず、「作風の説明文が
# 判定根拠にならないこと」だけを見る。
AUTHOR_ARTICLE_STYLE_EXTRACT = (
    "吾妻 ひでお（あづま ひでお、1950年2月6日 - 2019年10月13日）は、日本の漫画家。"
    "同年、『週刊少年サンデー』で、初の週刊誌連載となる『ざ・色っぷる』を連載するが、"
    "6回で連載終了。"
    "このころ、ページ内の1コマを1コママンガとして完結させるという試みを多く行っている。"
)

# Issue #37: 実際の『8マン インフィニティ』の記事から抜粋。「完結していない」は完結の
# *否定*であり、強シグナルとして扱えばまったく逆の意味になる。この記事では同じ文に
# 「連載終了」があるため結論は偶然一致していたが、それに依存しないことを確認する。
NEGATED_COMPLETION_EXTRACT = (
    "『8マン インフィニティ』（エイトマン インフィニティ）は、原作：七月鏡一、"
    "作画：鷹氏隆之による日本の漫画作品。\n\n\n"
    "== 概要 ==\n"
    "2004年より2007年にかけて講談社発行の漫画雑誌『月刊マガジンZ』にて連載された。"
    "連載終了時点では全くストーリーは完結していないが、原作者である七月は"
    "「あくまでも「第一部完」です」との見解を示している。"
)

# Issue #45: 実際の漫画家記事『押切蓮介』の冒頭。一次分類が「漫画家・歌手」と複数の職業を
# 並べる形で、語尾（歌手）だけを見ると人物と判別できない。区切り記号で分割した*先頭*
# セグメントを見る理由がこれである。M6-D-2ではこの記事に`ジーニアース`が着地し、別作品
# 『おののけ！くわいだん部』等の連載状況を根拠に「連載中」と誤答していた。
AUTHOR_ARTICLE_MULTI_OCCUPATION_EXTRACT = (
    "押切 蓮介（おしきり れんすけ、本名：神崎良太、1979年9月19日 - ）は、"
    "日本の漫画家・歌手。"
    "2022年現在、怪談専門誌『怪と幽』にて『おののけ！くわいだん部』、"
    "『月刊ビッグガンガン』にて『ハイスコアガールDASH』を連載中。"
)

# Issue #45: 実際の『魔法少女メルル』の冒頭。**作品記事なのに一次分類が「漫画家・…」で
# 始まる**という、`_is_person_article`にとって唯一の危険形（実在）。「『」で始まるか
# どうかのガードが無いと、この形の作品記事を誤って「記事なし」に落とす。
WORK_ARTICLE_WITH_AUTHOR_PRIMARY_TYPE_EXTRACT = (
    "『魔法少女メルル』（まほうしょうじょ メルル）は、日本の漫画家・ねこしたPONGによる"
    "成人向け漫画、および、それを原作としてメディアミックスで作られた作品群の"
    "メインタイトルである。"
    "漫画はアダルトゲーム雑誌『ファンタジェンヌ』にて1993年（平成5年）から1995年に"
    "かけて執筆された。"
)

# Issue #45: 実際の『陰陽師 (漫画)』のリード文。冒頭文に「日本の<種別>」が無く
# （「夢枕獏の小説『陰陽師』を原作とする岡野玲子の漫画。」）、`_PRIMARY_TYPE_RE`が
# 一致しない記事の代表例。作品記事200件中35件がこの形で、`_is_person_article`を
# fail-closedにするとこれらが全滅する。
#
# あわせてIssue #41（mediamix緩和）の対象そのものでもある。この記事は`小説`を含む
# リード文のせいで`_is_novel_primary()`が真を返し、判定文に漫画マーカーが無いため
# 判定不能に落ちている。#45は記事*選定*だけを変える修正なので、この偽陰性は
# 手つかずのまま残っていなければならない（下の回帰テスト参照）。
ONMYOJI_EXTRACT = (
    "『陰陽師』（おんみょうじ）は、夢枕獏の小説『陰陽師』を原作とする岡野玲子の漫画。"
    "1993年から2005年に、『コミックバーガー』『コミックバーズ』（いずれもスコラ）、"
    "『月刊メロディ』（白泉社）で連載された。"
    "2006年、第37回星雲賞コミック部門を受賞している。"
    "続編に『陰陽師 玉手匣』がある。"
)


def test_one_piece_is_ongoing():
    status, evidence = _judge_extract(ONE_PIECE_EXTRACT)
    assert status == "連載中"
    assert "連載中" in evidence


def test_shingeki_no_kyojin_is_completed():
    # 回帰テスト: 冒頭文が「小説」を派生作品として列挙しているだけの漫画原作作品を、
    # 一次分類(「日本の漫画」)で正しく単一メディア扱いし、判定不能に倒さないこと。
    status, evidence = _judge_extract(SHINGEKI_EXTRACT)
    assert status == "完結"
    assert "完結した" in evidence


def test_dandadan_is_ongoing():
    status, evidence = _judge_extract(DANDADAN_EXTRACT)
    assert status == "連載中"


def test_ao_no_hako_past_tense_serialization_is_completed():
    # 「〜まで連載された」という過去形は、現在形の「連載中」と誤判定してはならない。
    status, evidence = _judge_extract(AO_NO_HAKO_EXTRACT)
    assert status == "完結"
    assert "まで連載された" in evidence


def test_tensura_manga_status_is_not_confused_with_novel_status():
    # 回帰テスト: 原作ライトノベルは完結しているが、漫画(コミカライズ)は連載中。
    # 単純な語検出だと原作小説側の「完結した」を拾ってしまうリスクがある。
    status, evidence = _judge_extract(TENSURA_EXTRACT)
    assert status == "連載中"
    assert "漫画" in evidence


def test_hunter_hunter_weekly_serialization_ending_is_not_completed():
    # 回帰テスト（実際に本番で誤判定したケース）: 「週刊連載を終了」だけを見て完結と
    # 判定していたが、同じ文で「継続」を発表しており、実際には連載中（休載を繰り返して
    # いるだけで終了していない）。判定不能側に倒すのが正しい（記事内に「連載中」
    # 「連載されている」という明確な現在形の表現が無いため、連載中と断定はできない）。
    status, evidence = _judge_extract(HUNTER_HUNTER_EXTRACT)
    assert status == STATUS_UNKNOWN


def test_yu_yu_hakusho_still_completed_without_continuation_veto():
    # HUNTER×HUNTERの修正（継続の語があるとCOMPLETED_WEAK_REを無効化する）が、
    # 継続を示す語の無い正当な完結判定まで壊していないことの確認。
    status, evidence = _judge_extract(YU_YU_HAKUSHO_EXTRACT)
    assert status == "完結"
    assert "連載された" in evidence


def test_tonkatsu_dj_agetaro_main_completion_not_confused_with_spinoff():
    # 回帰テスト（実際に本番で誤判定していたケース、Issue #13）: 本編自身の完結文
    # 「まで毎週木曜更新で連載。」は当時取りこぼされ、代わりに番外編の連載終了文が
    # 本編の判定文として採用されていた。SPINOFF_MARKERSによる除外と「まで...連載」の
    # 間隔緩和の両方が効いて、正しく本編自身の文から完結と判定できることを確認する。
    status, evidence = _judge_extract(TONKATSU_DJ_AGETARO_EXTRACT)
    assert status == "完結"
    assert "番外編" not in evidence
    assert "毎週木曜更新で連載" in evidence


def test_nichijou_serialization_resumption_across_comma_is_not_completed():
    # 回帰テスト（実際に本番で誤判定していたケース、Issue #38）: 「10月まで読み切りを
    # 掲載したのち、同年11月から連載に移行。」は読点をまたいで「まで」と「連載」が
    # 20文字以内に収まってしまい、連載の*開始*を述べる文なのに完結と誤爆していた。
    # 読点をまたぐ場合を除外した結果、この文からは完結・連載中のどちらの断定もできなく
    # なる（後続文の「連載を一旦終了するも、再開したが、休載となっている」も、
    # CONTINUATION_VETO_REが同一文内しか見ないため、あるいはONGOING_REに一致しない
    # ため決着しない）。断定できない以上、判定不能に倒すのが正しい
    # （Issue #8以来のfail-closed方針）。最低限守るべきは「完結」という誤った断定を
    # 返さないことである。
    status, _ = _judge_extract(NICHIJOU_EXTRACT)
    assert status != "完結"
    assert status == STATUS_UNKNOWN


def test_magazine_transfer_across_sentences_is_not_completed():
    # M6-B-3対応の回帰テスト（実データ「一緒に暮らしていいですか?」で誤判定していた形）:
    # 「Aまで連載。」で決着させず、走査範囲内の「連載されている」を根拠に連載中と判定する。
    status, evidence = _judge_extract(MAGAZINE_TRANSFER_ONGOING_EXTRACT)
    assert status == "連載中"
    assert "連載されている" in evidence


def test_other_works_serialization_end_does_not_make_main_work_completed():
    # M6-B-3対応の回帰テスト（実データ「サタノファニ」で誤判定していた形）: 本編の文が
    # 両シグナルを含んで曖昧なため、別作品の「連載終了」を代用してはならない。
    # 本編について断定できない以上、連載中ではなく判定不能に倒すのが正しい。
    status, _ = _judge_extract(OTHER_WORK_COMPLETION_EXTRACT)
    assert status == STATUS_UNKNOWN


def test_judge_extract_resolves_same_sentence_migration_buresu():
    # Issue #134（テーマA、作業84-3の設計根拠1件目）: 「まで…連載されたのち、
    # …移籍し…連載中」という同一文内の移籍構文を連載中として決着させる。
    status, evidence = _judge_extract(BURESU_MIGRATION_EXTRACT)
    assert status == "連載中"
    assert "連載中" in evidence


def test_judge_extract_resolves_same_sentence_migration_blondie():
    # Issue #134（テーマA、作業84-3の設計根拠2件目）: 「連載終了後は…で連載されている」
    # という、ブレスとは異なる接続語（後）・異なる連載中表現（連載されている）の組でも
    # 決着できることの確認。
    status, evidence = _judge_extract(BLONDIE_MIGRATION_EXTRACT)
    assert status == "連載中"
    assert "連載されている" in evidence


def test_migration_same_sentence_requires_connector():
    # MIGRATION_SAME_SENTENCE_REは接続語（のち／その後／後）を必須とする。接続語が
    # 無い場合は、Issue #134導入前と同じく同一文内競合としてスキップされ、判定不能の
    # ままであることを確認する（陰性対照。接続語の要求を外す変異が入るとこのテストが
    # 拾う）。
    status, _ = _judge_extract(NO_CONNECTOR_MIGRATION_EXTRACT)
    assert status == STATUS_UNKNOWN
    assert not MIGRATION_SAME_SENTENCE_RE.search(
        "『週刊サンプルX』にて2017年から2023年まで連載され、『サンプルWebY』でも連載中。"
    )


def test_judge_extract_resolves_kepitai_distribution_completion_via_haishin_sareta():
    # Issue #135（テーマB、作業87-2の設計根拠）: 「配信された」（過去形）を完結の
    # 弱シグナルとして認識する。
    status, evidence = _judge_extract(HAISHIN_SARETA_EXTRACT)
    assert status == "完結"
    assert "配信された" in evidence


def test_haishin_sareteiru_present_tense_does_not_trigger_completion():
    # 陰性対照（作業86-3で実測した誤検知リスクの回帰防止）: 「配信されている」
    # （現在形、継続中の配信を意味しうる）は「配信された」とは異なる語尾のため
    # 一致せず、判定不能のままであることを確認する。COMPLETED_WEAK_REへ「配信」を
    # 語幹単独で追加する変異が入ると、このテストが拾う。
    status, _ = _judge_extract(HAISHIN_SARETEIRU_EXTRACT)
    assert status == STATUS_UNKNOWN
    assert not COMPLETED_WEAK_RE.search("『例のサイト』にて2007年から配信されている。")


def test_strong_completion_is_not_vetoed_by_ongoing_elsewhere():
    # M6-B-3の無効化が弱シグナル限定であることの担保（Issue #8以来の方針）。
    # 「完結」（強シグナル）は、走査範囲内に別の連載中シグナルがあっても無効化しない。
    # 作品名自体に「完結」を含めるとタイトルの文がCOMPLETED_STRONG_REに一致してしまい、
    # 本来検査したい文とは別の文が根拠に採用されるため、無関係な作品名にしている。
    #
    # Issue #154（案B）: 別作品を示す文にSPINOFF_MARKERSタグ（「スピンオフ」等）を
    # 使うと、_has_ongoing_signal()がその文を走査から除外するようになり、
    # has_ongoing_elsewhereが常にFalseになってveto自体が発火しなくなる
    # （このテストの意図が空洞化する）。案B適用後もveto判定が実際に発火した状態を
    # 保つため、SPINOFF_MARKERSタグの付かない語「リメイク版」に差し替えた
    # （has_ongoing_signal()の戻り値が修正前後とも変わらずTrueのままであることを
    # 実測で確認済み）。
    #
    # 「リメイク版」は現行コーパス（holdout99+regression61、160件）には実在しない
    # 合成表現である。SPINOFF_MARKERSに含まれず、かつONGOING_REと共起する形で
    # 「本編とは別の作品」を示す語は、160件の実データ走査（
    # docs/code_defects_2026-08/mutation_candidate_search_result.md）でも
    # 見つからなかった（該当する56文全てが本編自身の掲載状況を直接述べる文のみ
    # だった）。実在する代替語が無いため、この合成表現をそのまま使う。
    extract = (
        "『例の終了作品』は、某作者による日本の漫画作品。"
        "本編は2020年に完結した。"
        "リメイク版『例の終了作品Rebirth』は現在も連載中。"
    )
    status, evidence = _judge_extract(extract)
    assert status == "完結"
    assert "完結した" in evidence


def test_spinoff_completion_does_not_override_main_series_ongoing_status():
    # 合成フィクスチャ（実データでは未発見）: 本編が連載中、番外編が完結済みという、
    # とんかつDJアゲ太郎の実例とは逆に食い違うパターン。番外編の完結文につられて
    # 誤って「完結」を返さないことを確認する。
    status, evidence = _judge_extract(SPINOFF_COMPLETED_MAIN_ONGOING_EXTRACT)
    assert status == "連載中"
    assert "番外編" not in evidence


def test_jojo_is_ongoing_via_present_progressive_form():
    # 「連載されている」という、既存フィクスチャの「連載中」とは異なる現在形表現でも
    # 連載中と判定できることの確認（M6-D-1）。
    status, evidence = _judge_extract(JOJO_EXTRACT)
    assert status == "連載中"
    assert "連載されている" in evidence


def test_berserk_is_ongoing():
    # 作者急逝後も連載が継続している実世界の事例（M6-D-1）。
    status, evidence = _judge_extract(BERSERK_EXTRACT)
    assert status == "連載中"


def test_kochikame_original_serialization_completion_is_not_vetoed():
    # 回帰テスト（M6-D-1・Issue #11）: 「まで連載され、その後も新作が作られている」は
    # HUNTER×HUNTERと表面的に似た構造だが、意図的にCONTINUATION_VETO_REの対象にして
    # いない。週刊連載という一つの物語は完結しており、その後の新作は不定期の
    # アニバーサリー的な追加作品という性質の違いがあるため（詳細はCLAUDE.md参照）。
    status, evidence = _judge_extract(KOCHIKAME_EXTRACT)
    assert status == "完結"
    assert "新作が作られている" in evidence


def test_oooku_non_predicative_ongoing_does_not_suppress_completion():
    # 回帰テスト（Issue #36 / 実データ「大奥」）: 「連載中から多くの漫画賞を受賞し」は
    # 受賞時期を述べる修飾語であって、現在の連載状況ではない。これを連載シグナルとして
    # 扱うと、正しい完結文が抑止されたうえにこの文自身が採用され、完結済みの作品を
    # 「連載中」と断定してしまう（M6-D-2で観測された唯一の誤った断定）。
    status, evidence = _judge_extract(OOOKU_EXTRACT)
    assert status == "完結"
    assert "2021年2月号まで連載された" in evidence


def test_other_works_ongoing_mention_does_not_suppress_completion():
    # 回帰テスト（Issue #36 / 実データ「鋼の錬金術師」）: 「同誌の連載中作品の中では」は
    # 他作品への言及であり、本作の状況ではない。抑止されると正しい完結文が使えなくなり、
    # その文自身も両シグナルを持つため採用されず、判定不能に落ちる（偽陰性）。
    status, evidence = _judge_extract(HAGANE_NO_RENKINJUTSUSHI_EXTRACT)
    assert status == "完結"
    assert "2010年7月号まで連載された" in evidence


def test_author_article_residence_sentence_is_not_an_ongoing_signal():
    # 回帰テスト（Issue #36 / 実データ「小田扉」）: 「『団地ともお』連載中の2016年より
    # …在住」は居住開始時期を述べる文で、連載シグナルではない。
    # ここで検証するのは`_judge_extract`レベルの挙動のみ。この記事に着地する行
    # （こさめちゃん・横須賀こずえ）が行として「記事なし」に倒れることは、記事選定側で
    # 解決した（Issue #45）ので、そちらのend-to-endテストで固定している
    # （`test_judge_rejects_author_article_reached_via_redirect`）。
    assert _has_ongoing_signal(AUTHOR_ARTICLE_RESIDENCE_EXTRACT) is False

    _, evidence = _judge_extract(AUTHOR_ARTICLE_RESIDENCE_EXTRACT)
    assert evidence is None or "在住" not in evidence


def test_ongoing_episodic_work_is_not_completed_by_self_contained_format_phrase():
    # 回帰テスト（Issue #37 / 実データ「絶体絶命でんぢゃらすじーさん」）: 「一話完結型」は
    # 各話が独立して終わる作品形式を指す定型句で、作品の終了とは無関係。強シグナルは
    # veto の対象外なので、これを COMPLETED_STRONG_RE に一致させると抑止できず、
    # 連載中の作品を確信を持って`完結`と誤答する（実際にそうなっていた）。
    status, evidence = _judge_extract(DENJARASU_JIISAN_EXTRACT)
    assert status == "連載中"
    assert "2025年12月号から連載中" in evidence


def test_self_contained_format_phrase_does_not_flip_completed_work_to_ongoing():
    # 回帰テスト（Issue #37 / 実データ「ARIA (漫画)」）: 「1話完結形式」の誤爆を止めると、
    # それまで強シグナルの陰に隠れていた「連載中に」（ONGOING_REの非述語用法・Issue #36と
    # 同クラス）が露出し、完結済みの作品が`連載中`に転ぶ。COMPLETED_STRONG_RE と
    # ONGOING_RE の両方の除外が揃って初めてこのテストは通る。
    assert _has_ongoing_signal(ARIA_EXTRACT) is False

    status, evidence = _judge_extract(ARIA_EXTRACT)
    assert status == "完結"
    assert "1話完結形式で月刊誌に連載された" in evidence


def test_episodic_format_sentences_are_not_used_as_evidence():
    # 回帰テスト（Issue #37 / 実データ「アウターゾーン」）: 「各話完結」と、語順が逆の
    # 「完結する回」の両方が作風の説明として出てくる。ステータスは結果的に正しかったが、
    # 判定根拠の列に作風の説明文が入っていた（こち亀と同じパターン）。
    status, evidence = _judge_extract(OUTER_ZONE_EXTRACT)
    assert status == "完結"
    assert "各話完結" not in evidence
    assert "完結する回" not in evidence
    assert "連載終了後に発表された" in evidence


def test_author_article_style_sentence_is_not_a_completion_signal():
    # 回帰テスト（Issue #37 / 実データ「吾妻ひでお」＝`リングサイドクレイジー`の着地先）:
    # 「1コマを1コママンガとして完結させる」は作風の説明であって連載状況ではない。
    # ここで検証するのは`_judge_extract`レベルの挙動のみ。`リングサイドクレイジー`が
    # 行として「記事なし」に倒れることは記事選定側で解決した（Issue #45）ので、
    # そちらのend-to-endテストで固定している。
    _, evidence = _judge_extract(AUTHOR_ARTICLE_STYLE_EXTRACT)
    assert evidence is None or "1コママンガ" not in evidence


def test_is_person_article_detects_author_articles():
    # Issue #45: 作者記事の一次分類は語尾が「家」で一貫している。「漫画家・歌手」のように
    # 複数の職業が並ぶ形（押切蓮介）があるため、区切り記号で分割した先頭セグメントを見る。
    for extract in (
        AUTHOR_ARTICLE_STYLE_EXTRACT,  # 吾妻ひでお（日本の漫画家）
        AUTHOR_ARTICLE_RESIDENCE_EXTRACT,  # 小田扉（日本の漫画家）
        AUTHOR_ARTICLE_MULTI_OCCUPATION_EXTRACT,  # 押切蓮介（日本の漫画家・歌手）
    ):
        assert _is_person_article(extract) is True, extract[:30]


def test_is_person_article_does_not_reject_work_articles():
    # Issue #45: 作品記事を人物と誤判定すると、正しく判定できていた行が「記事なし」に
    # 落ちる。実測400件では誤除外0件だったが、その根拠になった3つの形を固定する。
    for extract in (
        ONE_PIECE_EXTRACT,  # 一次分類が「少年漫画」
        OOOKU_EXTRACT,  # 一次分類が「フィクション・時代物の少女漫画」
        ONMYOJI_EXTRACT,  # 冒頭文に「日本の<種別>」が無い（作品記事200件中35件がこの形）
        WORK_ARTICLE_WITH_AUTHOR_PRIMARY_TYPE_EXTRACT,  # 一次分類が「漫画家・…」で始まる
    ):
        assert _is_person_article(extract) is False, extract[:30]


def test_is_person_article_falls_open_on_malformed_extracts():
    # Issue #45: 判定できないときは必ずfail-open（人物ではない）に倒す。
    # `_is_novel_primary()`はfail-closedだが、こちらで同じ既定値にすると、冒頭文に
    # 「日本の<種別>」が無い作品記事（実測200件中35件）が軒並み「記事なし」に落ちる。
    for extract in (
        "",
        "   ",
        "吾妻ひでおは日本の漫画家",  # 句点が1つも無く、冒頭1文を切り出せない
    ):
        assert _is_person_article(extract) is False, repr(extract)


def test_negated_completion_is_not_a_completion_signal():
    # Issue #37: 「完結していない」「未完結」「完結せず」は完結の*否定*であり、完結
    # シグナルになる余地が論理的に無い。実データ（8マン インフィニティ・GOLDEN BOY・
    # BUILD KING）ではいずれも同じ文に「連載終了」「打ち切り」があって結論が偶然一致して
    # いたため、単体でも正しく扱えることを正規表現レベルで確認する。
    for phrase in (
        "連載終了時点では全くストーリーは完結していない。",
        "ストーリーは未完結のまま連載が止まっている。",
        "本誌では物語が完結せずに終了した。",
        "話の本筋は完結しないまま放置されている。",
    ):
        assert COMPLETED_STRONG_RE.search(phrase) is None, phrase

    # 否定形の除外に巻き込まれず、本来の完結表現は引き続き強シグナルであること。
    for phrase in (
        "1994年3月号にて完結した。",
        "2009年7月号に完結する。",
        "本編は2020年に完結し、その後スピンオフが始まった。",
        "最終回で完結する。",
    ):
        assert COMPLETED_STRONG_RE.search(phrase) is not None, phrase


def test_negated_completion_sentence_does_not_decide_on_its_own():
    # 回帰テスト（Issue #37 / 実データ「8マン インフィニティ」）: 「完結していない」を
    # 含む文が判定根拠として採用されないこと。この記事では別の文（連載された）が正しく
    # 完結を示すため、ステータス自体は`完結`のままでよい。
    status, evidence = _judge_extract(NEGATED_COMPLETION_EXTRACT)
    assert status == "完結"
    assert "完結していない" not in evidence


def test_ongoing_signal_ignores_non_predicative_usages():
    # Issue #36: 除外する形は実測で誤爆したものに限る（「だっ」「であっ」は過去の状態を
    # 表す形で、現在連載中であることを意味しうる余地が無いため実例なしで含めている）。
    for sentence in (
        "連載中から多くの漫画賞を受賞した。",
        "単行本は連載中は全200巻。",
        "同誌の連載中作品の中では最長連載された作品である。",
        "『団地ともお』連載中の2016年より神奈川県横須賀市在住。",
        "連載中だった当時は毎週徹夜だったという。",
        "連載中であった頃の逸話が知られている。",
        # Issue #37の作業中に見つかった同クラスの取りこぼし（実データ「ARIA (漫画)」）。
        "連載中にエニックスお家騒動が起こり、移籍にあたって改題した。",
        # Issue #141（作業92・96、実データ「百合男子」）: 「連載中断」は連載継続の否定
        # （中断そのもの）であり、正反対の意味。
        "（2016年1月号掲載分を最後に連載中断）",
        # Issue #141（作業92・96、実データ「ゆうれい小僧がやってきた!」）: 「連載中に」と
        # 同型の副詞的用法だが、直後が読点で終わる形。
        "また連載中、怪現象に見舞われてお祓いをしてもらったり、"
        "「子供が怖がるから怖い妖怪を描かないで下さい」という苦情の手紙も来たという。",
    ):
        assert _has_ongoing_signal(sentence) is False, sentence


def test_ongoing_signal_still_detects_predicative_usages():
    # Issue #36の除外が広すぎないことの担保。述語位置の「連載中」と、名詞が続く正当な形
    # （「連載中の漫画」）は従来どおり連載シグナルとして扱う。
    for sentence in (
        "『週刊少年ジャンプ』（集英社）にて1997年34号から連載中。",
        "漫画版は『月刊少年シリウス』にて連載中で、32巻まで刊行されている。",
        "『ビッグコミックオリジナル』では『百年川柳』などを連載（2015年現在も連載中）。",
        "現在も連載中の漫画である。",
        "『ヤングアニマル』にて2007年14号から連載されている。",
    ):
        assert _has_ongoing_signal(sentence) is True, sentence


def test_death_note_part_numbers_are_not_mistaken_for_partial_completion():
    # 回帰テスト（M6-D-1）: 「第一部」「第二部」は掲載号の内訳表記であり、シリーズの
    # 一部だけの完結ではない。将来M6-B-2に対応する際もこの完結判定を壊してはならない。
    status, evidence = _judge_extract(DEATH_NOTE_EXTRACT)
    assert status == "完結"


def test_gotakeshi_cancellation_is_treated_as_completed():
    # 仕様確定済み（M6-B-1）: 「打ち切り」は円満な完結と同じ「完結」ステータスに含める。
    # ただし判定根拠には打ち切りだった事実がそのまま残る。
    status, evidence = _judge_extract(GOTAKESHI_EXTRACT)
    assert status == "完結"
    assert "打ち切り" in evidence


def test_near_cancellation_that_was_avoided_is_not_completed():
    # 回帰テスト（M6-B-1）: 「打ち切りの危機に瀕したが連載は継続した」のように、
    # 打ち切られなかった文脈では完結と判定してはならない（継続語による無効化）。
    status, evidence = _judge_extract(NEAR_CANCELLATION_EXTRACT)
    assert status == STATUS_UNKNOWN


def test_multimedia_work_with_no_manga_specific_sentence_is_unknown():
    status, evidence = _judge_extract(TENSURA_NO_MANGA_SENTENCE_EXTRACT)
    assert status == STATUS_UNKNOWN
    assert evidence is None


def test_extract_with_no_status_sentence_is_unknown():
    status, evidence = _judge_extract("『何か』は、誰かによる日本の漫画作品。")
    assert status == STATUS_UNKNOWN
    assert evidence is None


def _manga_infobox_block(fields):
    lines = ["{{Infobox animanga/Manga"]
    for key, value in fields:
        lines.append(f"|{key} = {value}")
    lines.append("}}")
    return "\n".join(lines)


# Issue #12: 事前調査（転生したらスライムだった件・呪術廻戦・NARUTO -ナルト-）で確認した
# 構造を模した合成フィクスチャ。本編ブロックは`タイトル`欄が無く、スピンオフブロックは
# 明示的な`タイトル`欄を持つ。
# Issue #56: 終了系が空欄なだけでは`連載中`と断定しなくなったので、継続の証拠
# （`巻数`の`既刊`表記）を持たせる。**値そのものは上と同じく合成である**（実在の記事から
# 採った値ではない）。形は M6-D-4（Issue #53）で実測した実データに倣っており、たとえば
# `うしろの正面カムイさん`の`既刊12巻（2026年2月現在）`が同じ形。実値は
# `scripts/m6d4_labels.py` に96行分ある。
# この経路が誤りやすいことの根拠: 実データ1,800件の調査で、この経路が`連載中`と答えた
# 75行のうち46行（61.3%）が実際には完結していた。
MAIN_BLOCK_ONGOING = _manga_infobox_block(
    [
        ("作者", "[[某作者]]"),
        ("出版社", "[[集英社]]"),
        ("開始号", "2015年1号"),
        ("巻数", "既刊20巻（2026年6月現在）"),
        ("終了号", ""),
        ("終了日", ""),
    ]
)

# Issue #56: 終了系は空欄だが継続の証拠が無い形（合成）。実データではこの形の61.3%が
# 完結していたので、`連載中`と断定せず判定不能に倒す。
MAIN_BLOCK_NO_EVIDENCE = _manga_infobox_block(
    [
        ("作者", "[[某作者]]"),
        ("出版社", "[[集英社]]"),
        ("開始号", "2015年1号"),
        ("巻数", "全12巻"),
        ("終了号", ""),
        ("終了日", ""),
    ]
)

MAIN_BLOCK_COMPLETED = _manga_infobox_block(
    [
        ("作者", "[[某作者]]"),
        ("出版社", "[[集英社]]"),
        ("開始号", "2015年1号"),
        ("終了号", "2020年30号"),
        ("終了日", "2020年7月10日"),
    ]
)

# Issue #156（`prereg_lineage2_infobox_placeholder.md`）: 終了系フィールドの値が
# 「？」「?」のみの未確定プレースホルダである場合、根拠の無い完結断定を避ける。
MAIN_BLOCK_PLACEHOLDER_FULLWIDTH = _manga_infobox_block(
    [
        ("作者", "[[某作者]]"),
        ("出版社", "[[集英社]]"),
        ("開始号", "2015年1号"),
        ("終了号", "？"),
    ]
)

MAIN_BLOCK_PLACEHOLDER_HALFWIDTH = _manga_infobox_block(
    [
        ("作者", "[[某作者]]"),
        ("出版社", "[[集英社]]"),
        ("開始号", "2015年1号"),
        ("終了号", "?"),
    ]
)

SPINOFF_BLOCK = _manga_infobox_block(
    [
        ("タイトル", "サンプル外伝"),
        ("作者", "[[某作者]]"),
        ("開始号", "2019年1号"),
        ("終了号", "2019年12号"),
    ]
)

SPINOFF_BLOCK_2 = _manga_infobox_block(
    [
        ("タイトル", "サンプル外伝2"),
        ("作者", "[[某作者]]"),
        ("終了号", "2021年5号"),
    ]
)

NO_END_FIELDS_BLOCK = _manga_infobox_block(
    [
        ("作者", "[[某作者]]"),
        ("出版社", "[[集英社]]"),
    ]
)

# {{small|...}}のようなネストしたテンプレートを含むブロックが、_extract_braced_blocksで
# 壊れずに1ブロックとして切り出せることの確認用。
NESTED_MAIN_BLOCK = (
    "{{Infobox animanga/Manga\n"
    "|作者 = [[某作者]]\n"
    "|出版社 = {{small|[[集英社]]}}\n"
    "|開始号 = 2015年1号\n"
    "|巻数 = 既刊20巻（2026年6月現在）\n"
    "|終了号 = \n"
    "|終了日 = \n"
    "}}"
)


def test_judge_via_infobox_main_block_is_ongoing_when_end_fields_are_empty():
    # HUNTER×HUNTER形: 本編ブロックの終了号/終了日が空欄で、かつ継続の証拠があれば連載中。
    wikitext = MAIN_BLOCK_ONGOING + "\n\n" + SPINOFF_BLOCK
    status, evidence = _judge_via_infobox(wikitext, today=date(2026, 7, 29))
    assert status == "連載中"
    assert "インフォボックス" in evidence


def test_judge_via_infobox_stays_unknown_without_continuation_evidence():
    # Issue #56: 空欄だけでは足りない。同じ構造でも継続の証拠が無ければ判定不能のまま。
    wikitext = MAIN_BLOCK_NO_EVIDENCE + "\n\n" + SPINOFF_BLOCK
    status, evidence = _judge_via_infobox(wikitext, today=date(2026, 7, 29))
    assert status is None
    assert evidence is None


def test_judge_via_infobox_main_block_is_completed_when_end_field_has_value():
    # こち亀形: 本編ブロックの終了号に値があれば完結。
    wikitext = MAIN_BLOCK_COMPLETED + "\n\n" + SPINOFF_BLOCK
    status, evidence = _judge_via_infobox(wikitext)
    assert status == "完結"
    assert "終了号 = 2020年30号" in evidence


def test_judge_via_infobox_finds_main_block_among_multiple_spinoffs():
    # 転スラ形: 本編1個+スピンオフ複数でも、本編ブロックが一意に特定できること。
    wikitext = MAIN_BLOCK_ONGOING + "\n\n" + SPINOFF_BLOCK + "\n\n" + SPINOFF_BLOCK_2
    status, evidence = _judge_via_infobox(wikitext)
    assert status == "連載中"


def test_judge_via_infobox_gives_up_when_two_titleless_blocks_exist():
    # 回帰テスト（Issue #12の完了条件）: タイトル欄なしのブロックが2個ある場合、
    # どちらが本編か確信を持てないため判定材料なしとして扱う。
    wikitext = MAIN_BLOCK_ONGOING + "\n\n" + MAIN_BLOCK_COMPLETED
    status, evidence = _judge_via_infobox(wikitext)
    assert status is None
    assert evidence is None


def test_judge_via_infobox_gives_up_when_no_titleless_block_exists():
    # 回帰テスト（Issue #12の完了条件）: 全ブロックにタイトル欄がある（=本編が無い）場合も
    # 同様に判定材料なしとして扱う。
    wikitext = SPINOFF_BLOCK + "\n\n" + SPINOFF_BLOCK_2
    status, evidence = _judge_via_infobox(wikitext)
    assert status is None
    assert evidence is None


def test_judge_via_infobox_gives_up_when_no_end_field_exists_at_all():
    # 回帰テスト: 終了系フィールドが1つも存在しない（検証済みの3作品と異なるスキーマの）
    # ブロックでは、連載中と決め付けず判定材料なしとして扱う。
    wikitext = NO_END_FIELDS_BLOCK + "\n\n" + SPINOFF_BLOCK
    status, evidence = _judge_via_infobox(wikitext)
    assert status is None
    assert evidence is None


def test_judge_via_infobox_placeholder_fullwidth_stays_unknown():
    # Issue #156: 終了号が「？」のみ（全角）の場合、根拠の無い完結断定を避け判定不能。
    wikitext = MAIN_BLOCK_PLACEHOLDER_FULLWIDTH + "\n\n" + SPINOFF_BLOCK
    status, evidence = _judge_via_infobox(wikitext)
    assert status is None
    assert evidence is None


def test_judge_via_infobox_placeholder_halfwidth_stays_unknown():
    # Issue #156: 終了号が「?」のみ（半角）の場合も同様に判定不能。
    wikitext = MAIN_BLOCK_PLACEHOLDER_HALFWIDTH + "\n\n" + SPINOFF_BLOCK
    status, evidence = _judge_via_infobox(wikitext)
    assert status is None
    assert evidence is None


def test_judge_via_infobox_numeric_end_field_still_completed():
    # Issue #156: 数字を含む通常値は変更前と同じく完結のまま（ネガティブコントロール）。
    wikitext = MAIN_BLOCK_COMPLETED + "\n\n" + SPINOFF_BLOCK
    status, evidence = _judge_via_infobox(wikitext)
    assert status == "完結"
    assert "終了号 = 2020年30号" in evidence


# M-5パターン対応（Issue #41調査、作業62〜63）: 終了系フィールドが非空欄でも、値が
# 「休載」を示す注記であれば終了とみなさない。`日常`の実データ（Measured 2026-08-10）を
# そのままフィクスチャにする。
#   終了号 = "2008年7月号〈一時休載〉"
#   巻数   = "既刊12巻（2024年10月25日現在）"（2026年基準で継続の証拠あり）
NICHIJOU_MAIN_BLOCK = _manga_infobox_block(
    [
        ("作者", "[[あらゐけいいち]]"),
        ("出版社", "[[KADOKAWA]]"),
        ("開始号", "2006年11月号"),
        ("終了号", "2008年7月号〈一時休載〉"),
        ("巻数", "既刊12巻（2024年10月25日現在）"),
    ]
)

# 「新たに壊れうるケース」（作業63）: 終了号に休載注記が残るが、継続の証拠が無い
# （実際に完結していておかしくない）形。合成フィクスチャ。fail-closed側
# （判定不能）に倒れることを固定する——完結とも連載中とも断定してはならない。
HIATUS_ANNOTATION_NO_EVIDENCE_BLOCK = _manga_infobox_block(
    [
        ("作者", "[[某作者]]"),
        ("出版社", "[[集英社]]"),
        ("開始号", "2001年1号"),
        ("終了号", "2015年3号（2010〜2012年休載）"),
        ("巻数", "全12巻"),
    ]
)


def test_judge_via_infobox_treats_hiatus_annotation_as_not_ended_nichijou():
    # 回帰テスト（実データ、Issue #41調査で発見）: 終了号が非空欄でも「休載」注記なら
    # 完結と断定せず、巻数の継続証拠（Issue #56）へフォールスルーする。
    wikitext = NICHIJOU_MAIN_BLOCK
    status, evidence = _judge_via_infobox(wikitext, today=date(2026, 8, 10))
    assert status == "連載中"
    assert "終了号 = 2008年7月号〈一時休載〉" in evidence
    assert "休載注記のため終了とみなさず" in evidence
    assert "巻数 = 既刊12巻（2024年10月25日現在）" in evidence


def test_judge_via_infobox_hiatus_annotation_without_continuation_evidence_stays_unknown():
    # 「新たに壊れうるケース」: 休載注記はあるが継続の証拠が無い（本当に完結している
    # かもしれない）合成フィクスチャ。完結とも連載中とも断定せず判定不能に倒れることを
    # 固定する（fail-closed）。
    wikitext = HIATUS_ANNOTATION_NO_EVIDENCE_BLOCK
    status, evidence = _judge_via_infobox(wikitext, today=date(2026, 8, 10))
    assert status is None
    assert evidence is None


# Issue #142（作業92のjudge()実測で発見）: 終了系フィールドの値自体が「連載中」という
# 実データ（`猫mix幻奇譚とらじ`、Measured 2026-08-13）をそのままフィクスチャにする。
#   終了号 = "連載中"
#   巻数   = "既刊14巻（2025年3月現在）"
NEKOMIX_MAIN_BLOCK = _manga_infobox_block(
    [
        ("作者", "[[田村由美]]"),
        ("出版社", "[[小学館]]"),
        ("開始号", "2007年"),
        ("終了号", "連載中"),
        ("巻数", "既刊14巻（2025年3月現在）"),
    ]
)


def test_judge_via_infobox_treats_ongoing_field_value_as_not_ended_nekomix():
    # 回帰テスト（実データ、Issue #142）: 終了号が非空欄でも値自体が「連載中」なら
    # 完結と断定せず、継続の証拠（Issue #56）を経由せず直接連載中を返す。
    wikitext = NEKOMIX_MAIN_BLOCK
    status, evidence = _judge_via_infobox(wikitext, today=date(2026, 8, 13))
    assert status == "連載中"
    assert "終了号 = 連載中" in evidence


def test_extract_braced_blocks_handles_nested_templates():
    wikitext = NESTED_MAIN_BLOCK + "\n\n== 概要 ==\n本文の説明。"
    blocks = _extract_braced_blocks(wikitext, MANGA_INFOBOX_MARKER)
    assert len(blocks) == 1
    assert blocks[0] == NESTED_MAIN_BLOCK
    assert "概要" not in blocks[0]


def test_strip_annotations_removes_mixed_width_and_nested_brackets():
    # 実データ（M6-E-1）で観測した書き方。「(特装版がない場合通常版）」は開き括弧が
    # 半角・閉じ括弧が全角という混在、「（電子版のみ【最終巻】5巻が発売済）」は入れ子。
    assert _strip_annotations("カッコウの許嫁　(特装版ない場合通常版)") == "カッコウの許嫁"
    assert _strip_annotations("夫婦以上、恋人未満。(特装版がない場合通常版）") == "夫婦以上、恋人未満。"
    assert (
        _strip_annotations("触手魔術師の成り上がり（電子版のみ【最終巻】5巻が発売済）")
        == "触手魔術師の成り上がり"
    )
    assert _strip_annotations("普通のタイトル") == "普通のタイトル"


def test_strip_trailing_note_cuts_at_fullwidth_space_or_wave_dash():
    assert _strip_trailing_note("月曜日のたわわ　青版") == "月曜日のたわわ"
    assert _strip_trailing_note("終わりのハテミは繁殖したい　③～定期") == "終わりのハテミは繁殖したい"
    assert _strip_trailing_note("朝まで恋愛chu！ ～幼なじみはトキめかない？") == "朝まで恋愛chu！"
    # 半角スペースは区切りにしない（記事名の一部でありうるため）。
    assert _strip_trailing_note("お隣の天使様 after the rain") == "お隣の天使様 after the rain"


def test_title_variants_are_ordered_by_confidence_and_deduplicated():
    assert _title_variants("ドラゴン") == ["ドラゴン"]
    assert _title_variants("グラぱらっ！") == ["グラぱらっ！", "グラぱらっ!"]
    assert _title_variants("月曜日のたわわ　青版") == [
        "月曜日のたわわ　青版",
        "月曜日のたわわ 青版",
        "月曜日のたわわ",
    ]
    # 注記除去 → 後置注記除去の順に確信度が下がる。
    assert _title_variants("姫騎士がクラスメート！　ＴＨＥ　ＣＯＭＩＣ") == [
        "姫騎士がクラスメート！　ＴＨＥ　ＣＯＭＩＣ",
        "姫騎士がクラスメート! THE COMIC",
        "姫騎士がクラスメート！",
        "姫騎士がクラスメート!",
    ]


def test_original_title_is_probed_before_any_stripped_form():
    # 注記除去・後置注記除去が正規タイトルを壊さないことの担保。加工した文字列は原文の
    # *後ろ* にしか並ばないため、括弧や全角スペースを正規タイトルの一部として含む作品でも、
    # 実在する原文の記事が必ず先に採用される（加工形はそれが存在しないときの保険）。
    #
    # 以下の4件は、実データでこの形の入力を観測したわけではなく、構造（変種の順序）を
    # 検証するために構成した例である。実在する作品名を含むが、利用者がこの表記で入力
    # した実績があるという主張ではない。実データ由来の入力例は
    # test_strip_annotations_... / test_strip_trailing_note_... 側にある。
    for title in (
        "ぼくらの（仮）",
        "推しの子【推し】",
        "とある魔術の禁書目録 (アニメ)",
        "ノーゲーム・ノーライフ　ゼロ",
    ):
        variants = _title_variants(title)
        assert variants[0] == title
        assert _strip_annotations(title) != title or _strip_trailing_note(title) != title, (
            "加工で変化しない例を混ぜても順序の担保にならないため、変化する例を使うこと"
        )


def test_search_queries_are_capped_and_normalization_duplicates_dropped():
    # NFKC正規化しただけの変種は、全文検索では原文と同じ結果になるため別クエリにしない。
    assert _search_queries(_title_variants("グラぱらっ！")) == ["グラぱらっ！"]
    assert _search_queries(_title_variants("月曜日のたわわ　青版")) == [
        "月曜日のたわわ　青版",
        "月曜日のたわわ",
    ]


def _search_response(titles):
    return {"query": {"search": [{"title": t} for t in titles]}}


def _extract_response(title, extract, missing=False):
    page = {"title": title}
    if missing:
        page["missing"] = ""
    else:
        page["extract"] = extract
    return {"query": {"pages": {"1": page}}}


# 以降の judge() レベルのテストは、記事選定の *経路*（どの変種・どの裏付けで記事に
# 辿り着くか）の検査が目的であり、判定ロジックそのものは検査対象外である。そのため
# リード文には既存の合成フィクスチャ（主に ONE_PIECE_EXTRACT）を流用しており、
# 「連載中」という判定結果自体には意味がない ―― 記事が採用されたかどうかを読み取る
# ための目印として使っている。判定ロジックの回帰は _judge_extract() 直呼びの
# テスト群（ファイル前半）が担当する。


def _resolve_response(existing=(), missing=(), redirects=(), normalized=()):
    """`_resolve_titles`が投げる action=query&titles=A|B&redirects=1 の応答を組み立てる。

    existing/missing は「Wikipedia側で最終的に解決された記事名」、redirects/normalized は
    (from, to) のタプル列。
    """
    pages = {}
    for i, title in enumerate(existing, start=1):
        pages[str(i)] = {"title": title}
    for i, title in enumerate(missing, start=1):
        pages[str(-i)] = {"title": title, "missing": ""}
    query = {"pages": pages}
    if redirects:
        query["redirects"] = [{"from": f, "to": t} for f, t in redirects]
    if normalized:
        query["normalized"] = [{"from": f, "to": t} for f, t in normalized]
    return {"query": query}


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


# --- 記事選択系の直接呼び出しテスト（作業67、行・分岐カバレッジ100%だが直接テストが
# 0件だった5関数への対応） -----------------------------------------------------------
#
# judge()レベルのテストは「最終的な判定結果」しか見ないため、これらの関数固有の
# ロジック（リダイレクト解決の順序、tried集合の重複処理等）を壊しても、既存
# フィクスチャの最終出力がたまたま変わらなければ検出できない（ERRORS.md参照）。
# 各関数について、まず単独で保証すべき契約を明記してからテストを書く。


def test_resolve_titles_returns_empty_dict_for_empty_input_without_api_call():
    """契約: _resolve_titles([])は{}を返し、APIを一切叩かない。"""
    with patch("comic_checker.wikipedia_client.requests.get") as mock_get:
        result = _resolve_titles([])
    assert result == {}
    assert mock_get.call_count == 0


def test_resolve_titles_gives_up_when_redirect_chain_exceeds_max_hops():
    """契約: リダイレクト/正規化の連鎖が_MAX_REDIRECT_HOPSを超えて続く場合、
    そのタイトルは解決されず結果から欠落する（無限ループ防止のfail-closed）。"""
    nodes = [f"hop{i}" for i in range(_MAX_REDIRECT_HOPS + 1)]
    chain = list(zip(nodes, nodes[1:]))
    response = _response(_resolve_response(existing=[nodes[-1]], redirects=chain))
    with patch("comic_checker.wikipedia_client.requests.get", return_value=response):
        result = _resolve_titles([nodes[0]])
    assert result == {}


def test_pick_via_direct_lookup_does_not_retry_a_page_already_tried_by_an_earlier_probe():
    """契約: 複数のprobeが同じ解決済みページに着地した場合、そのページへの
    _accept_article呼び出し（延いては記事取得）は1回だけで、2件目以降のprobeは
    tried集合でスキップされる——後続probeがtrusted=Trueになる形でも、である。

    最初のprobe「○○」は素タイトルでtrusted=False、内容チェックで却下される。
    2件目のprobe「○○ (漫画)」は同じページに解決しtrusted=Trueになるはずだが、
    tried集合が効いていればそもそも再訪問されない。もしtried判定が壊れていれば、
    2件目が信頼経路として内容チェック無しに採用され、結果がNoneでなくなる
    （かつAPI呼び出しが1回増える）ため、この壊れ方を検出できる。
    """
    probes = ["○○", "○○ (漫画)"]
    resolve_response = _response(
        _resolve_response(
            existing=["○○記事"],
            redirects=[("○○", "○○記事"), ("○○ (漫画)", "○○記事")],
        )
    )
    extract_response = _response(_extract_response("○○記事", "何の変哲もない説明文。"))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, extract_response],
    ) as mock_get:
        article, trace = _pick_via_direct_lookup(probes, "○○")

    assert article is None
    assert trace is None
    assert mock_get.call_count == 2  # resolve 1回 + 記事取得1回。2回目の取得は起きない。


def test_lands_on_a_different_work_true_when_gate_open_and_extract_names_input_as_derivative():
    """契約: 着地先タイトル（曖昧さ回避接尾辞除去後）が入力と異なり、かつ着地先の
    リード文が入力を派生作品として紹介していればTrue。"""
    assert (
        _lands_on_a_different_work(
            "彼女、お借りします", KANOJO_OKARISHIMASU_EXTRACT, "彼女、人見知ります"
        )
        is True
    )


def test_lands_on_a_different_work_gate_closes_on_title_match_regardless_of_extract():
    """契約: 着地先タイトルが（曖昧さ回避接尾辞を除けば）入力と一致する場合、
    リード文の内容に関わらず即座にFalse——ゲートはリード文を読む前に閉じる。

    ここでは「派生作品として紹介している」と読めるはずのextract
    （KANOJO_OKARISHIMASU_EXTRACT）をあえて渡し、それでもFalseになることで
    ゲートの短絡が実際に効いていることを固定する。
    """
    assert (
        _lands_on_a_different_work(
            "彼女、人見知ります (漫画)", KANOJO_OKARISHIMASU_EXTRACT, "彼女、人見知ります"
        )
        is False
    )


def test_is_about_manga_true_when_relevance_marker_present():
    """契約: ARTICLE_RELEVANCE_MARKERSのいずれかがリード文に含まれればTrue。"""
    assert _is_about_manga(ONE_PIECE_EXTRACT) is True


def test_is_about_manga_false_when_no_relevance_marker_present():
    """契約: マーカーが1つも含まれなければFalse。"""
    assert _is_about_manga("これは無関係な説明文です。") is False


def test_pick_article_returns_direct_lookup_result_without_calling_search(monkeypatch):
    """契約: 直参照（_pick_via_direct_lookup）が記事を見つけたら、それをそのまま返し、
    検索（_pick_via_search）は一切呼ばない。"""
    sentinel = (("記事", "リード文", "https://example/記事"), "trace-sentinel")
    monkeypatch.setattr(
        wikipedia_client, "_pick_via_direct_lookup", lambda probes, title: sentinel
    )
    search_calls = []
    monkeypatch.setattr(
        wikipedia_client,
        "_pick_via_search",
        lambda *args, **kwargs: search_calls.append((args, kwargs)),
    )

    result = _pick_article("タイトル")

    assert result == sentinel
    assert search_calls == []


def test_pick_article_falls_back_to_search_when_direct_lookup_finds_nothing(monkeypatch):
    """契約: 直参照が(None, None)を返した場合、検索へフォールバックしその結果を返す。

    回帰テスト（Issue #39）: `(None, None)`はPythonでは真値なので、
    `_pick_via_direct_lookup(...) or _pick_via_search(...)`のように`or`で書くと
    このフォールバックが起きず、直参照側の(None, None)がそのまま返ってしまう。
    明示的な`result[0] is not None`チェックが必要（現行実装）。
    """
    monkeypatch.setattr(
        wikipedia_client, "_pick_via_direct_lookup", lambda probes, title: (None, None)
    )
    sentinel = (None, None)
    search_calls = []

    def fake_search(variants, already_probed, input_title):
        search_calls.append((variants, already_probed, input_title))
        return sentinel

    monkeypatch.setattr(wikipedia_client, "_pick_via_search", fake_search)

    result = _pick_article("タイトル")

    assert result == sentinel
    assert len(search_calls) == 1


# --- 作業68: 作業67でスコープ外とした残る未カバー分岐 ------------------------------------


def test_pick_via_search_skips_a_candidate_already_probed_by_direct_lookup(monkeypatch):
    """契約: 候補が`already_probed`（直参照で既に試行済み）に含まれる場合、
    その候補への`_accept_article`呼び出しをスキップし、次の候補へ進む。

    このテストが単独で検知できる壊れ方: `if candidate in already_probed: continue`が
    無くなり、直参照で既に不採用と分かっている記事へ検索経由で再度アクセスする
    リグレッション（`_accept_article`が余分に呼ばれる）。
    """
    monkeypatch.setattr(wikipedia_client, "_search_queries", lambda variants: ["謎の作品"])
    monkeypatch.setattr(
        wikipedia_client, "_search_titles", lambda query, limit=5: ["謎の作品 (漫画)"]
    )
    accept_calls = []

    def fake_accept(page_title, trusted, input_title):
        accept_calls.append(page_title)
        return None

    monkeypatch.setattr(wikipedia_client, "_accept_article", fake_accept)

    article, trace = _pick_via_search(
        variants=["謎の作品"], already_probed={"謎の作品 (漫画)"}, input_title="謎の作品"
    )

    assert article is None
    assert trace is None
    assert accept_calls == []


def test_pick_via_search_accepts_the_second_candidate_when_the_first_is_rejected(
    monkeypatch,
):
    """契約: 検索結果は上位1件だけでなく全件を見る——最初の候補が`_accept_article`に
    拒否されても、ループは継続して次の候補を試す。

    このテストが単独で検知できる壊れ方: 最初の候補で`return`/ループ終了してしまい、
    2件目以降を一切試さなくなるリグレッション（上位1件しか見ない実装への後退）。
    """
    monkeypatch.setattr(wikipedia_client, "_search_queries", lambda variants: ["謎の作品"])
    monkeypatch.setattr(
        wikipedia_client,
        "_search_titles",
        lambda query, limit=5: ["謎の作品 (漫画)", "謎の作品"],
    )
    fake_article = ("謎の作品", "リード文", "https://example/謎の作品")

    def fake_accept(page_title, trusted, input_title):
        return None if page_title == "謎の作品 (漫画)" else fake_article

    monkeypatch.setattr(wikipedia_client, "_accept_article", fake_accept)

    article, trace = _pick_via_search(
        variants=["謎の作品"], already_probed=set(), input_title="謎の作品"
    )

    assert article == fake_article
    assert trace.probe == "謎の作品"


def test_accept_article_returns_none_when_fetch_extract_finds_nothing(monkeypatch):
    """契約: `_fetch_extract`が記事を見つけられなかった場合（None）、
    `_accept_article`はNoneを返す——後続の内容チェックへは進まない。

    trusted=Falseで確認する（作業68で気づいた自分の設計ミスの修正）: 当初
    trusted=Trueで書いたが、trusted=Trueの分岐は`article`をそのまま
    `return`するだけなので、ガードを消してもarticle自体がNoneのままで
    結果が変わらず、ミューテーションを検知できなかった（trusted=Trueが
    たまたま同じ結果になるだけで、ガードの必要性を検証できていなかった）。
    trusted=Falseなら、ガードが無いと後続の`_is_about_manga(article[1])`が
    `None[1]`で例外になり、確実に区別できる。

    このテストが単独で検知できる壊れ方: `if article is None: return None`が
    無くなり、Noneを後続の内容チェックに渡して例外になるリグレッション。
    """
    monkeypatch.setattr(wikipedia_client, "_fetch_extract", lambda page_title: None)

    result = _accept_article("存在しない記事", trusted=False, input_title="タイトル")

    assert result is None


def test_is_person_article_false_when_first_sentence_has_no_primary_type_pattern():
    """契約: 冒頭1文が句点で区切れて存在する（＝空文字・句点無しではない）が、
    `_PRIMARY_TYPE_RE`（「日本の<種別>」パターン）自体に一致しない場合も、
    人物記事とはみなさない（fail-open）。

    既存のfail-openテスト（`falls_open_on_malformed_extracts`）は「句点が無く
    冒頭1文を切り出せない」形のみをカバーしており、「句点はあるが
    `_PRIMARY_TYPE_RE`に一致しない」形は別の分岐（L341）である。「日本の」という
    リテラルを含まない冒頭文（フランスの漫画家）で区別する。

    このテストが単独で検知できる壊れ方: `match is None`のときの既定値がFalse
    以外に変わり、fail-openの原則が崩れるリグレッション。
    """
    extract = "サンプル太郎はフランスの漫画家である。"
    assert _is_person_article(extract) is False


def test_judge_extract_skips_a_decisive_sentence_that_also_names_a_spinoff():
    """契約: 非mediamix作品で、決着（ongoing/completed）文がSPINOFF_MARKERSも
    含む場合、その文は本編の判定材料として採用せずスキップし、走査を続ける。

    既存の`test_spinoff_completion_does_not_override_main_series_ongoing_status`は
    弱シグナル（COMPLETED_WEAK_RE）＋M6-B-3のveto（has_ongoing_elsewhere）で
    先に`continue`するため、実はこの分岐（SPINOFF_MARKERSチェック自体）を
    通らない（作業68で実測確認）。ここでは強シグナル（COMPLETED_STRONG_RE、
    veto対象外）を使い、SPINOFF_MARKERSチェックそのものを踏ませる。

    このテストが単独で検知できる壊れ方: SPINOFF_MARKERSチェックが外れ、
    外伝の完結文を本編の判定として誤採用するリグレッション（結果が
    `完結`になってしまう）。
    """
    extract = "『本編』は、某作者による日本の漫画。外伝「本編外伝」は完結した。『週刊誌』にて連載中。"
    status, evidence = _judge_extract(extract)
    assert status == "連載中"
    assert "完結した" not in evidence


def test_judge_extract_skips_next_generation_spinoff_setogiwa_hanayome():
    """回帰テスト（実データ、Issue #144・#154）: 「次世代編」を含む文は、本編
    （セトギワ花ヨメ自身）ではなく子ども世代を主役とする派生作品の連載開始を
    述べているに過ぎないため、本編の判定として採用してはならない——これがIssue
    #144が守ろうとしたものであり、案B適用後も変わらず成立している。

    Issue #144時点の期待値は「判定不能」だったが、これは「セトギワ花ヨメの真の
    状態が判定不能である」という主張ではなく、次世代編の文をSPINOFF_MARKERSで
    除外した結果、（当時は）他に決着文が無くなるという構造的な帰結だった
    （PR #146）。真の状態は`~/comic_checker-agent-notes/step95_2_labels_final.json`
    に「完結」として記録済み（本編は2023年8月号まで連載、終了号/終了日記載）。

    案B（Issue #154）適用後、`_has_ongoing_signal()`も次世代編の文を走査から
    除外するようになったため、`has_ongoing_elsewhere`veto（M6-B-3）が発火しなく
    なり、本編自身の完結文（弱シグナル、「…2005年6月号より2023年8月号まで連載。」）
    が取り消されずに採用され、真の状態「完結」に到達するようになった
    （E_missed→A_correct）。Issue #144が防いだ「次世代編の連載中文を本編の判定
    として誤採用し『連載中』と誤答する」という危険な誤り（D_error）には戻って
    いない——次世代編の文は引き続きSPINOFF_MARKERSで除外され、判定文として採用
    されることはない。

    このテストが単独で検知できる壊れ方: SPINOFF_MARKERSから「次世代編」が
    外れ（またはそもそも追加されず）、次世代編の連載開始文を本編の判定として
    誤採用し「連載中」と誤答するリグレッション。
    """
    status, evidence = _judge_extract(SETOGIWA_HANAYOME_EXTRACT)
    assert status == "完結"
    assert "2023年8月号まで連載" in evidence


def test_judge_extract_skips_spinoff_sentence_in_multimedia_path_saijaku_teimaa():
    """回帰テスト（実データ、Issue #144）: is_multimedia=True経路（原作ライトノベル＋
    コミカライズのメディアミックス作品）でも、SPINOFF_MARKERSチェックが両経路共通で
    適用され、スピンオフ漫画の連載文が本編の判定として採用されないこと。除外した結果
    他に決着文が無いため判定不能に倒れる。

    このテストが単独で検知できる壊れ方: SPINOFF_MARKERSチェックがis_multimedia=True
    分岐の外（is_multimedia=False専用）に戻り、is_multimedia=True経路では
    スピンオフ漫画の連載文（「連載された」＝COMPLETED_WEAK_RE、かつMANGA_MARKERSの
    「漫画」を含みNOVEL_MARKERSを含まないため無条件に採用される）がそのまま
    本編の判定として誤採用され「完結」と誤答するリグレッション。
    """
    status, evidence = _judge_extract(SAIJAKU_TEIMAA_EXTRACT)
    assert status == STATUS_UNKNOWN
    assert evidence is None


# Issue #151（作業98-B抜き取り測定で発見、実データ）。同一ファイル内の
# DERIVATIVE_WORK_MARKERS（Issue #51）には既に「続編」が含まれているのに、
# SPINOFF_MARKERSには無かった非対称性が原因で、別題続編「バーテンダー6stp」に
# ついての「連載されている」という文が、本編『バーテンダー à Tokyo』自身の
# 完結文（「2016年1号から同年7号まで連載。」）の代わりに判定文として誤採用され、
# 「連載中」と誤答していた（正しくは「完結」）。
BARTENDER_A_TOKYO_EXTRACT = (
    "『バーテンダー à Tokyo』（バーテンダー ア トーキョー）は、原作：城アラキ、"
    "作画：加治佐修による日本の漫画作品。『グランドジャンプ』（集英社）にて、"
    "2013年23号から2015年23号まで連載した後、『グランドジャンプPREMIUM』"
    "（同社刊）に掲載誌を移した後に2016年1号から同年7号まで連載。\n"
    "『バーテンダー à Paris』の直接の続編で、主人公も同じ。"
    "本作の続編として『バーテンダー6stp』が『グランドジャンプPREMIUM』で"
    "連載されている。\n"
)


def test_judge_extract_excludes_zokuhen_sentence_bartender_a_tokyo():
    """回帰テスト（実データ、Issue #151・#154）: SPINOFF_MARKERSに「続編」を含める
    ことで、別題続編についての連載中文を本編の判定として採用しない。

    Issue #154（案B）適用後、`_has_ongoing_signal()`もSPINOFF_MARKERSタグ付きの
    文を走査から除外するようになったため、Issue #30由来のhas_ongoing_elsewhere
    vetoが続編文の「連載されている」を拾わなくなった。これにより、本編自身の
    完結文（弱シグナル、「…2016年1号から同年7号まで連載。」）の取り消しが解除され、
    `_judge_extract`単体で「完結」に到達するようになった（案B適用前は判定不能に
    倒れ、`judge()`のインフォボックス・フォールバック経由でしか完結に到達できな
    かった）。

    このテストが単独で検知できる壊れ方: SPINOFF_MARKERSから「続編」が外れ（または
    そもそも追加されず）、別題続編の連載中文を本編の判定として誤採用し
    「連載中」と誤答するリグレッション。
    """
    status, evidence = _judge_extract(BARTENDER_A_TOKYO_EXTRACT)
    assert status == "完結"
    assert "2016年1号から同年7号まで連載" in evidence


# Issue #151（作業98-B抜き取り測定で発見、実データ）。前作『ジーザス』（本編とは
# 別作品）の連載期間を述べる「…の続編である。」という文が、本編『JESUS 砂塵航路』
# 自身の判定文として誤採用されていた。誤採用されたまま出力された「完結」は、
# たまたま正解ラベルと一致していたに過ぎない（本来の正しい根拠はインフォボックスの
# 終了フィールドであり、`_judge_extract`が誤った文で先に決着してしまうと、
# `judge()`のインフォボックス・フォールバックへ到達できず本来の正しい根拠を
# 参照できない）。
JESUS_SAJIN_KORO_EXTRACT = (
    "『JESUS 砂塵航路』（ジーザス さじんこうろ）は、七月鏡一原作・藤原芳秀作画に"
    "よる日本の漫画。\n\n\n"
    "== 概要 ==\n"
    "1992年から1995年まで『週刊少年サンデー』に連載された『ジーザス』"
    "（以下「前作」）の続編である。2009年2月20日から、小学館の携帯コミックサイト"
    "『モバMAN』にて配信されていた。話数カウントは前作と同じく「Lesson.○」。"
    "単行本は全14巻。\n"
)


def test_judge_extract_excludes_zokuhen_sentence_jesus_sajin_koro():
    """回帰テスト（実データ、Issue #151）: 前作（別作品）の連載終了を述べる
    「…の続編である。」という文を、本編自身の判定として採用しない。

    除外した結果、本編自身について走査範囲内に他の決着文が無いため判定不能に
    倒れる（「配信されていた」はCOMPLETED_WEAK_REの「配信された」と活用形が
    異なり一致しない。この語彙ギャップは別のIssue候補として扱う）。

    このテストが単独で検知できる壊れ方: SPINOFF_MARKERSから「続編」が外れ、
    前作の連載終了文を本編自身の判定として誤採用し、`status == "完結"`かつ
    `evidence`に前作名『ジーザス』を含む文字列を返すリグレッション。
    """
    status, evidence = _judge_extract(JESUS_SAJIN_KORO_EXTRACT)
    assert status == STATUS_UNKNOWN
    assert evidence is None


# --- 作業70: 69-2(b)で分類Aとしたレスポンス解析系の残り未カバー箇所 ----------------------
#
# L494（_mentions_as_derivative_work の空白正規化タイトル分岐）は対象外とする。
# 69-2で「実データでの再現性は薄い」と自己評価しており、分類B寄りのため今回は書かない。


def test_is_novel_primary_falls_back_to_novel_markers_when_no_primary_type_match():
    """契約: `_PRIMARY_TYPE_RE`（「日本の<種別>」パターン）が一致しない場合、
    NOVEL_MARKERSがextract中に含まれるかどうかでフォールバック判定する
    （fail-closed: 判定できないときは小説主体とみなす）。

    既存フィクスチャONMYOJI_EXTRACT（陰陽師の実データ、Issue #41）をそのまま
    使う——「日本の<種別>」パターンには一致しないが「小説」を含むため、この
    分岐を正確に踏む。

    このテストが単独で検知できる壊れ方: フォールバック時の既定値がFalse側に
    変わり、mediamixチェックがfail-open（危険側）に倒れるリグレッション。
    """
    assert _is_novel_primary(ONMYOJI_EXTRACT) is True


def test_extract_braced_blocks_skips_an_unterminated_occurrence():
    """契約: markerの出現に対応する閉じ括弧が見つからない（不正なwikitext）場合、
    その出現はスキップし、次のmarker出現を探す——読み飛ばして処理を続ける
    （docstring: 「閉じ括弧が見つからない不正なwikitextの場合、その出現は
    スキップして次を探す」）。

    このテストが単独で検知できる壊れ方: スキップ処理が外れ、不正な1件目の
    ブロックを（閉じ括弧が無いまま）誤って切り出す、または2件目の正常な
    ブロックまで取りこぼすリグレッション。
    """
    block1_unterminated = "{{Infobox animanga/Manga\n|作者 = 不正\n"
    block2_valid = "{{Infobox animanga/Manga\n|作者 = 正常\n}}"
    wikitext = block1_unterminated + block2_valid

    blocks = _extract_braced_blocks(wikitext, MANGA_INFOBOX_MARKER)

    assert blocks == [block2_valid]


def test_lead_and_first_section_cuts_before_the_second_level2_heading():
    """契約: レベル2見出し（`== ... ==`）が2つ以上ある場合、2つ目の見出しの
    開始位置までで切る（導入部+最初のセクションのみに限定する、Issue #12）。

    このテストが単独で検知できる壊れ方: 切り出し位置がずれ、2番目以降の
    セクション（スピンオフ等の判定材料を含みうる）まで走査範囲に混入する
    リグレッション。
    """
    text = "導入部の文。\n\n== 概要 ==\n概要の本文。\n\n== 連載状況 ==\n連載状況の本文。\n"

    result = _lead_and_first_section(text)

    assert "連載状況の本文" not in result
    assert "概要の本文" in result


def test_fetch_extract_returns_none_when_pages_is_empty():
    """契約: APIレスポンスの`pages`が空（記事情報が一切返らない）場合、Noneを返す。

    このテストが単独で検知できる壊れ方: `pages`が空のときに`next(iter(...))`が
    `StopIteration`を投げて未処理の例外になるリグレッション。
    """
    response = _response({"query": {"pages": {}}})
    with patch("comic_checker.wikipedia_client.requests.get", return_value=response):
        result = _fetch_extract("存在しないタイトル")
    assert result is None


def test_fetch_extract_returns_none_when_page_is_missing():
    """契約: ページオブジェクトに`missing`キーがある（記事が存在しない）場合、
    たとえ`extract`フィールドに値があってもNoneを返す（`missing`優先）。

    `extract`に値を持たせるのは意図的——空extractの場合と混同すると、
    「missingチェックが外れて空文字列フォールバックに紛れ込む」壊れ方を
    このテストが検知できなくなる（L858の空extractガードと結果が縮退して
    区別がつかなくなるため）。

    このテストが単独で検知できる壊れ方: `missing`チェックが外れ、`missing`
    キーを無視して`extract`の内容をそのまま採用してしまうリグレッション。
    """
    response = _response(
        {"query": {"pages": {"1": {"title": "存在しないタイトル", "missing": "", "extract": "本来使われてはいけない内容"}}}}
    )
    with patch("comic_checker.wikipedia_client.requests.get", return_value=response):
        result = _fetch_extract("存在しないタイトル")
    assert result is None


def test_fetch_extract_returns_none_when_extract_is_empty():
    """契約: `extract`フィールドが空文字列（strip後も空）の場合、Noneを返す。

    このテストが単独で検知できる壊れ方: 空文字列チェックが外れ、空のリード文を
    持つ`(タイトル, "", url)`をそのまま採用してしまうリグレッション
    （後続の`_is_about_manga("")`等が誤って判定不能ではなく確信を持った
    誤答に倒れる経路を開く）。
    """
    response = _response(_extract_response("記事名", ""))
    with patch("comic_checker.wikipedia_client.requests.get", return_value=response):
        result = _fetch_extract("記事名")
    assert result is None


def test_fetch_wikitext_returns_none_when_wikitext_is_empty():
    """契約: `parse.wikitext.*`が空文字列（またはキー自体が無い）場合、Noneを返す。

    このテストが単独で検知できる壊れ方: 空文字列チェックが外れ、空のwikitextを
    そのまま返してしまい、呼び出し側（`_judge_via_infobox`）が空文字列を本編
    ブロック抽出にかけて誤った判定材料無し状態を隠すリグレッション。
    """
    response = _response({"parse": {"wikitext": {"*": ""}}})
    with patch("comic_checker.wikipedia_client.requests.get", return_value=response):
        result = _fetch_wikitext("記事名")
    assert result is None


def test_judge_prefers_direct_manga_disambiguation_page():
    resolve_response = _response(
        _resolve_response(
            existing=["転生したらスライムだった件 (漫画)"], missing=["転生したらスライムだった件"]
        )
    )
    extract_response = _response(
        _extract_response("転生したらスライムだった件 (漫画)", TENSURA_EXTRACT)
    )

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, extract_response],
    ) as mock_get:
        result = judge("転生したらスライムだった件")

    assert isinstance(result, WikipediaJudgment)
    assert result.status == "連載中"
    assert result.matched_title == "転生したらスライムだった件 (漫画)"
    # 変種をまとめて実在確認する1回 + 採用した記事のリード文を取る1回で済み、検索は行わない。
    assert mock_get.call_count == 2


def test_adoption_path_constants_have_the_expected_literal_values():
    """4つのADOPTION_PATH_*定数を、本番側と同じシンボルではなくリテラル文字列と
    比較して固定する（作業44、claude-review.ymlのレビュー指摘への対応）。

    この下の判定系テスト（例: test_judge_records_disambiguation_adoption_path_
    for_yojo_senki）は`result.adoption_path == ADOPTION_PATH_DIRECT_DISAMBIGUATION`
    のように**本番側と同じインポート済みシンボル同士**を比較していたため、
    定数の値そのものを変異させても両側が追従し、1件も落ちなかった
    （CLAUDE.mdの「新しい定数を導入したら変異させて落ちることを確認する」、
    ERRORS.md「定数を期待値と入力の両方に使うテストは、定数を変えても
    落ちない」Issue #40と同型の穴。claude-review.yml run 31196492212の
    レビューが指摘し、`ADOPTION_PATH_DIRECT_DISAMBIGUATION`の値を
    `"MUTATED_VALUE"`に変えても`verify.sh`が`225 passed`のまま通ることを
    実測で再現・確認済み）。このテストはリテラル文字列と比較するため、
    定数の値そのものが変われば必ず落ちる。
    """
    assert ADOPTION_PATH_DIRECT_DISAMBIGUATION == "direct_disambiguation"
    assert ADOPTION_PATH_DIRECT_PLAIN == "direct_plain"
    assert ADOPTION_PATH_SEARCH_EXACT == "search_exact"
    assert ADOPTION_PATH_SEARCH_SUBTITLE == "search_subtitle"


def test_judge_records_disambiguation_adoption_path_for_yojo_senki():
    """Issue #39完了条件: 幼女戦記の入力で、「(漫画)」経由のtrusted採用が
    起きているかを出力（adoption_path/adoption_trusted/adoption_probe）から
    判別できること。判定ロジック自体（status）は検査対象外。
    """
    resolve_response = _response(
        _resolve_response(existing=["幼女戦記 (漫画)"], missing=["幼女戦記"])
    )
    extract_response = _response(_extract_response("幼女戦記 (漫画)", ONE_PIECE_EXTRACT))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, extract_response],
    ):
        result = judge("幼女戦記")

    assert result.matched_title == "幼女戦記 (漫画)"
    assert result.adoption_path == ADOPTION_PATH_DIRECT_DISAMBIGUATION
    assert result.adoption_trusted is True
    assert result.adoption_probe == "幼女戦記 (漫画)"


def test_judge_follows_wikipedia_redirect_to_the_real_article():
    # 「彼女、人見知ります」→「彼女、お借りします」のように、編集者が意図的に張った
    # リダイレクトは直参照の段階（`_resolve_titles`のredirects解決）で辿られる。
    resolve_response = _response(
        _resolve_response(
            existing=["実際の記事"],
            missing=["ダミー (漫画)"],
            redirects=[("ダミー", "実際の記事")],
        )
    )
    extract_response = _response(_extract_response("実際の記事", ONE_PIECE_EXTRACT))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, extract_response],
    ) as mock_get:
        result = judge("ダミー")

    assert result.matched_title == "実際の記事"
    assert result.status == "連載中"
    assert mock_get.call_count == 2


def test_judge_finds_article_that_differs_only_in_character_width():
    # 回帰テスト（M6-E-1）: 利用者が全角で書いたタイトル（「グラぱらっ！」）に対し、
    # Wikipediaの記事名は半角の感嘆符（「グラぱらっ!」）で立っている。`titles=`はUnicode
    # 正規化をしてくれないため、NFKC正規化した変種も併せて実在確認する必要がある。
    resolve_response = _response(
        _resolve_response(
            existing=["グラぱらっ!"],
            missing=["グラぱらっ！ (漫画)", "グラぱらっ! (漫画)", "グラぱらっ！"],
        )
    )
    extract_response = _response(_extract_response("グラぱらっ!", ONE_PIECE_EXTRACT))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, extract_response],
    ) as mock_get:
        result = judge("グラぱらっ！")

    assert result.matched_title == "グラぱらっ!"
    assert result.status == "連載中"
    assert mock_get.call_count == 2


def test_judge_records_direct_plain_adoption_path():
    """素タイトルの直参照（(漫画)表記ではない）で採用された場合の経路情報
    （Issue #39）。trustedはFalseになる。
    """
    resolve_response = _response(
        _resolve_response(existing=["グラぱらっ!"], missing=["グラぱらっ! (漫画)"])
    )
    extract_response = _response(_extract_response("グラぱらっ!", ONE_PIECE_EXTRACT))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, extract_response],
    ):
        result = judge("グラぱらっ!")

    assert result.matched_title == "グラぱらっ!"
    assert result.adoption_path == ADOPTION_PATH_DIRECT_PLAIN
    assert result.adoption_trusted is False
    assert result.adoption_probe == "グラぱらっ!"


def test_judge_strips_purchase_note_from_title():
    # 回帰テスト（M6-E-1）: 買い物メモ由来の括弧書き注記（全角/半角混在）を落とした
    # 変種でも実在確認する。
    resolve_response = _response(
        _resolve_response(
            existing=["カッコウの許嫁"],
            missing=[
                "カッコウの許嫁　(特装版ない場合通常版) (漫画)",
                "カッコウの許嫁 (漫画)",
                "カッコウの許嫁　(特装版ない場合通常版)",
            ],
        )
    )
    extract_response = _response(_extract_response("カッコウの許嫁", ONE_PIECE_EXTRACT))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, extract_response],
    ) as mock_get:
        result = judge("カッコウの許嫁　(特装版ない場合通常版)")

    assert result.matched_title == "カッコウの許嫁"
    assert result.status == "連載中"
    assert mock_get.call_count == 2


def test_judge_rejects_same_name_article_that_is_not_about_manga():
    # 回帰テスト（M6-E-1）: タイトル直参照で記事が実在しても、それが漫画の記事で
    # なければ採用しない（「ワンピース」＝衣類の記事を掴まないための歯止め）。
    resolve_response = _response(
        _resolve_response(existing=["ワンピース"], missing=["ワンピース (漫画)"])
    )
    unrelated_extract = _response(
        _extract_response("ワンピース", "ワンピースは、上半身と下半身がつながった女性用の衣類。")
    )
    empty_search = _response(_search_response([]))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, unrelated_extract, empty_search],
    ):
        result = judge("ワンピース")

    assert result.status == STATUS_NOT_FOUND
    assert result.matched_title is None


def test_judge_rejects_author_article_reached_via_redirect():
    # 回帰テスト（Issue #45 / 実データ「リングサイドクレイジー」）: 作品の記事が存在せず、
    # Wikipediaのリダイレクトが作者記事『吾妻ひでお』を指している行。作者記事のリード文は
    # 「…は、日本の漫画家。」なので`_is_about_manga`（「漫画」を含むか）を素通りしてしまい、
    # 記事中の*別作品*の連載状況を根拠に「完結」と誤答していた。期待値は「記事なし」。
    #
    # この行は#36（ONGOING_REの非述語用法）・#37（COMPLETED_STRONG_REの複合語誤爆）を
    # どちらも修正しても誤答のままだった。掴む文が変わるだけで、作者記事には別作品の
    # *それ自体としては正しい*連載状況の文がいくらでもあるためである。記事選定側でしか
    # 直せないことの実証そのものなので、語彙側のIssueで代用しないこと。
    resolve_response = _response(
        _resolve_response(
            existing=["吾妻ひでお"],
            missing=["リングサイドクレイジー (漫画)"],
            redirects=[("リングサイドクレイジー", "吾妻ひでお")],
        )
    )
    author_extract = _response(
        _extract_response("吾妻ひでお", AUTHOR_ARTICLE_STYLE_EXTRACT)
    )
    empty_search = _response(_search_response([]))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, author_extract, empty_search],
    ):
        result = judge("リングサイドクレイジー")

    assert result.status == STATUS_NOT_FOUND
    assert result.matched_title is None


def test_judge_rejects_author_article_for_residence_sentence_rows():
    # 回帰テスト（Issue #45 / 実データ「こさめちゃん」「横須賀こずえ」）: どちらも同じ
    # 作者記事『小田扉』に着地し、居住地の説明文を根拠に誤答していた2行。着地先が同一
    # なので、1件固定すれば両方を担保できる。
    resolve_response = _response(
        _resolve_response(
            existing=["小田扉"],
            missing=["こさめちゃん (漫画)"],
            redirects=[("こさめちゃん", "小田扉")],
        )
    )
    author_extract = _response(
        _extract_response("小田扉", AUTHOR_ARTICLE_RESIDENCE_EXTRACT)
    )
    empty_search = _response(_search_response([]))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, author_extract, empty_search],
    ):
        result = judge("こさめちゃん")

    assert result.status == STATUS_NOT_FOUND
    assert result.matched_title is None


def test_judge_still_returns_unknown_for_onmyoji_after_person_article_check():
    # 回帰テスト（Issue #45、#41の前提固定）: `陰陽師`は「陰陽師 (漫画)」という曖昧さ回避
    # 表記で解決するため信頼経路（trusted=True）に入り、人物記事チェックを一切通らない。
    # したがって#41が直そうとしている偽陰性（原作小説の存在でmediamix扱いになり判定不能に
    # 落ちる）は、#45の後も手つかずで残っていなければならない。
    #
    # これをテストで固定しておかないと、#41に着手したときに「前提が既に崩れていたのか、
    # 自分の変更で壊したのか」を判別できない。#41で緩和を入れた際は、このテストが
    # 「完結」を期待する形に変わるのが正しい。
    resolve_response = _response(
        _resolve_response(existing=["陰陽師 (漫画)"], missing=["陰陽師"])
    )
    extract_response = _response(_extract_response("陰陽師 (漫画)", ONMYOJI_EXTRACT))
    wikitext_error = _response(_wikitext_error_response())

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, extract_response, wikitext_error],
    ):
        result = judge("陰陽師")

    assert result.status == STATUS_UNKNOWN
    assert result.matched_title == "陰陽師 (漫画)"


def test_judge_rejects_search_candidate_without_exact_match_backing():
    # 回帰テスト（M6-A-1）: 検索結果の候補がクエリと（正規化後も）一致せず、
    # サブタイトル付きの形でもない場合、無関係な記事を確信を持って誤答するより
    # 記事なしに倒す。
    resolve_response = _response(_resolve_response(missing=["謎の作品 (漫画)", "謎の作品"]))
    search_response = _response(_search_response(["無関係な別の記事"]))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, search_response],
    ):
        result = judge("謎の作品")

    assert result.status == STATUS_NOT_FOUND
    assert result.matched_title is None


def test_judge_accepts_search_candidate_with_subtitle():
    # M6-E-1: 利用者は主題名しか書かないが、Wikipediaの記事名は副題込みで立っている
    # ことがある。区切り記号を挟んで主題名で始まる候補は採用する。
    resolve_response = _response(_resolve_response(missing=["謎の作品 (漫画)", "謎の作品"]))
    search_response = _response(_search_response(["無関係な別の記事", "謎の作品〜副題〜"]))
    extract_response = _response(_extract_response("謎の作品〜副題〜", ONE_PIECE_EXTRACT))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, search_response, extract_response],
    ):
        result = judge("謎の作品")

    assert result.status == "連載中"
    assert result.matched_title == "謎の作品〜副題〜"


def test_judge_records_search_subtitle_adoption_path_for_basilisk():
    """Issue #39完了条件: バジリスクの入力で、検索フォールバック（副題前方一致）
    経由の採用を経路情報（adoption_path）から判別できること。
    """
    resolve_response = _response(_resolve_response(missing=["バジリスク (漫画)", "バジリスク"]))
    search_response = _response(_search_response(["バジリスク 〜甲賀忍法帖〜"]))
    extract_response = _response(
        _extract_response("バジリスク 〜甲賀忍法帖〜", ONE_PIECE_EXTRACT)
    )

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, search_response, extract_response],
    ):
        result = judge("バジリスク")

    assert result.matched_title == "バジリスク 〜甲賀忍法帖〜"
    assert result.adoption_path == ADOPTION_PATH_SEARCH_SUBTITLE
    assert result.adoption_trusted is False
    assert result.adoption_probe == "バジリスク 〜甲賀忍法帖〜"


def test_judge_does_not_accept_search_candidate_that_merely_shares_a_prefix():
    # 「ギャルせん」に対する「ギャルせんぱいの秘密」のように、区切り記号を挟まず
    # 語が続くだけの別作品は採用しない。
    resolve_response = _response(_resolve_response(missing=["ギャルせん (漫画)", "ギャルせん"]))
    search_response = _response(_search_response(["ギャルせんぱいの秘密"]))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, search_response],
    ):
        result = judge("ギャルせん")

    assert result.status == STATUS_NOT_FOUND


def test_judge_returns_not_found_when_no_article_exists():
    resolve_response = _response(
        _resolve_response(missing=["存在しない作品 (漫画)", "存在しない作品"])
    )
    empty_search = _response(_search_response([]))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve_response, empty_search],
    ):
        result = judge("存在しない作品")

    assert result.status == STATUS_NOT_FOUND
    assert result.matched_title is None
    # Issue #39: 記事が見つからない場合、経路情報の3フィールドもすべてNoneのまま
    # （trace自体が無いことをそのまま伝える。fail-closedと同じ考え方）。
    assert result.adoption_path is None
    assert result.adoption_trusted is None
    assert result.adoption_probe is None


def test_pick_via_search_records_search_exact_adoption_path(monkeypatch):
    """search_exactの経路（検索候補が正規化後にexact集合と一致、副題ではない）。

    judge()経由のHTTPモックでこの分岐だけを再現するのは、直参照側の変種
    （_title_variantsが生成する正規化済み変種）と衝突しやすく難しいため、
    _pick_via_searchを直接呼び、判定ロジック（_accept_article）はモックして
    経路情報だけを検証する（Issue #39）。判定ロジック自体はテストしない
    （_accept_articleは固定のダミー記事を返すだけ）。
    """
    monkeypatch.setattr(wikipedia_client, "_search_queries", lambda variants: ["謎の作品"])
    monkeypatch.setattr(
        wikipedia_client, "_search_titles", lambda query, limit=5: ["謎の作品 (漫画)"]
    )
    fake_article = ("謎の作品 (漫画)", "リード文", "https://ja.wikipedia.org/wiki/謎の作品")
    monkeypatch.setattr(
        wikipedia_client,
        "_accept_article",
        lambda page_title, trusted, input_title: fake_article,
    )

    article, trace = _pick_via_search(
        variants=["謎の作品"], already_probed=set(), input_title="謎の作品"
    )

    assert article == fake_article
    assert trace.path == ADOPTION_PATH_SEARCH_EXACT
    assert trace.trusted is True
    assert trace.probe == "謎の作品 (漫画)"


def _wikitext_response(wikitext):
    return {"parse": {"title": "dummy", "wikitext": {"*": wikitext}}}


def _wikitext_error_response():
    return {"error": {"code": "missingtitle", "info": "The page you specified doesn't exist"}}


# Issue #12: 地の文には判定文が無い（=本文解析だけでは判定不能になる）合成フィクスチャ。
INFOBOX_PROBE_EXTRACT = "『インフォ実験作品』は、某作者による日本の漫画作品。"


def _infobox_probe_responses():
    """「インフォ実験作品」の直参照が「インフォ実験作品 (漫画)」に当たるまでの2応答。"""
    return [
        _response(
            _resolve_response(existing=["インフォ実験作品 (漫画)"], missing=["インフォ実験作品"])
        ),
        _response(_extract_response("インフォ実験作品 (漫画)", INFOBOX_PROBE_EXTRACT)),
    ]


def test_judge_does_not_fetch_wikitext_when_text_judgment_already_resolved():
    # 回帰テスト（Issue #12）: 本文解析で完結/連載中が確定している場合、
    # インフォボックス（action=parse）へのAPI呼び出しは発生しない。
    responses = [
        _response(_resolve_response(existing=["ワンピース (漫画)"], missing=["ワンピース"])),
        _response(_extract_response("ワンピース (漫画)", ONE_PIECE_EXTRACT)),
    ]

    with patch(
        "comic_checker.wikipedia_client.requests.get", side_effect=responses
    ) as mock_get:
        result = judge("ワンピース")

    assert result.status == "連載中"
    # 実在確認 + リード文取得の2回のみ（action=parseは呼ばれない）。
    assert mock_get.call_count == 2


def test_judge_upgrades_unknown_to_ongoing_via_infobox():
    wikitext_response = _response(
        _wikitext_response(MAIN_BLOCK_ONGOING + "\n\n" + SPINOFF_BLOCK)
    )

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=_infobox_probe_responses() + [wikitext_response],
    ) as mock_get:
        # Issue #56: 基準日を固定して渡す。実行日を使うとフィクスチャの`既刊…2026年`が
        # 5年後に古くなり、コードを変えていないのにテストが落ちる。
        result = judge("インフォ実験作品", today=date(2026, 7, 29))

    assert result.status == "連載中"
    assert "インフォボックス" in result.evidence
    assert mock_get.call_count == 3


def test_judge_use_infobox_false_skips_infobox_path_even_when_unknown():
    # 回帰テスト（Issue #16）: use_infobox=Falseのときは、本文解析が判定不能でも
    # インフォボックス経路（action=parse）を一切呼ばない。Issue #12前後の判定不能率を
    # 比較計測するための専用フラグであり、判定条件そのものは変更しないことの確認。
    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=_infobox_probe_responses(),
    ) as mock_get:
        result = judge("インフォ実験作品", use_infobox=False)

    assert result.status == STATUS_UNKNOWN
    assert mock_get.call_count == 2


def test_judge_does_not_let_infobox_declare_completed_against_prose_ongoing_signal():
    # M6-B-3対応の回帰テスト（実データ「サタノファニ」）: 本文に明確な「連載中」があるのに
    # 本文解析が決着しなかった場合、インフォボックスの終了系フィールドを根拠に完結と
    # 断定してはならない。移籍作品では終了日フィールドが「旧誌の終了日＋新誌での開始日」を
    # 記録することがあり、「値が入っている＝完結」が成り立たないため。
    # 本文の文はIssue #134のMIGRATION_SAME_SENTENCE_REには一致しない形にしてある
    # （「のち」「その後」「後」を使わない）。一致すると本文解析だけで連載中に決着して
    # しまい、このテストが検証したい「インフォボックスが本文の曖昧さを完結へ上書き
    # しない」という論点（本文解析が判定不能のまま止まるケース）を検査できなくなるため。
    ambiguous_extract = (
        "『例の曖昧作品』は、某作者による日本の漫画作品。"
        "『週刊サンプルA』にて2017年から2023年まで連載され、移籍先でも同年より連載中。"
    )
    responses = [
        _response(_resolve_response(existing=["例の曖昧作品 (漫画)"], missing=["例の曖昧作品"])),
        _response(_extract_response("例の曖昧作品 (漫画)", ambiguous_extract)),
        _response(_wikitext_response(MAIN_BLOCK_COMPLETED)),
    ]

    with patch("comic_checker.wikipedia_client.requests.get", side_effect=responses):
        result = judge("例の曖昧作品")

    assert result.status == STATUS_UNKNOWN


def test_judge_still_upgrades_to_completed_via_infobox_without_prose_ongoing_signal():
    # 上の抑止が広すぎないことの担保: 本文に連載中シグナルが無ければ、従来どおり
    # インフォボックスの終了系フィールドから完結へ引き上げてよい。
    responses = _infobox_probe_responses() + [
        _response(_wikitext_response(MAIN_BLOCK_COMPLETED))
    ]

    with patch("comic_checker.wikipedia_client.requests.get", side_effect=responses):
        result = judge("インフォ実験作品")

    assert result.status == "完結"
    assert "インフォボックス" in result.evidence


# Issue #143（作業92のjudge()実測で発見）、実際のWikipedia記事『宮廷神官物語』のリード文
# そのまま。原作ライトノベルの刊行情報のみで、漫画化への言及が一切無い
# （is_multimedia=True かつ 本文にMANGA_MARKERSが1つも出現しない）。
KYUUTEI_SHINKAN_MONOGATARI_EXTRACT = (
    "『宮廷神官物語』(きゅうていしんかんものがたり)は榎田ユウリによる日本の小説。"
    "角川ビーンズ文庫（角川書店）より2007年10月から2011年12月まで刊行された。"
)


def _kyuutei_probe_responses(extract=KYUUTEI_SHINKAN_MONOGATARI_EXTRACT):
    """『宮廷神官物語』の直参照が「宮廷神官物語」自身に当たるまでの2応答
    （disambiguation suffix「宮廷神官物語 (漫画)」は存在しない）。"""
    return [
        _response(
            _resolve_response(existing=["宮廷神官物語"], missing=["宮廷神官物語 (漫画)"])
        ),
        _response(_extract_response("宮廷神官物語", extract)),
    ]


def test_judge_does_not_let_infobox_declare_completed_for_novel_primary_work_without_manga_mention():
    """回帰テスト（実データ、Issue #143）: 本文（extract）が原作小説主体
    （is_multimedia=True）であり、かつ本文中に漫画化（コミカライズ）の言及が一切無い
    場合、インフォボックスの終了系フィールドが非空欄でも完結と断定してはならない。
    そのフィールドが本当に漫画の連載を指しているのか、本文からは確認できないため
    （fail-closed、M6-B-3のvetoと同じ判断枠組み）。

    このテストが単独で検知できる壊れ方: judge()内のこのvetoが外れ、原作小説の
    みが説明された記事でも漫画の完結を断定してしまうリグレッション。
    """
    wikitext_response = _response(_wikitext_response(MAIN_BLOCK_COMPLETED))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=_kyuutei_probe_responses() + [wikitext_response],
    ):
        result = judge("宮廷神官物語")

    assert result.status == STATUS_UNKNOWN


def test_judge_still_upgrades_to_completed_via_infobox_when_manga_mentioned_in_multimedia_work():
    """上の抑止が広すぎないことの担保（合成: KYUUTEI_SHINKAN_MONOGATARI_EXTRACTに
    コミカライズ言及を1文追加）。原作小説のメディアミックス作品でも、本文中に漫画化
    への言及があれば、従来どおりインフォボックス経由で完結へ引き上げてよい。

    このテストが単独で検知できる壊れ方: Issue #143のvetoがMANGA_MARKERSの有無を見ず
    is_multimedia=Trueだけで一律に抑止するよう壊れ、本文に漫画化の明記があっても
    判定不能に落ちてしまうリグレッション。
    """
    extract_with_manga = KYUUTEI_SHINKAN_MONOGATARI_EXTRACT + "コミカライズもされている。"
    wikitext_response = _response(_wikitext_response(MAIN_BLOCK_COMPLETED))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=_kyuutei_probe_responses(extract_with_manga) + [wikitext_response],
    ):
        result = judge("宮廷神官物語")

    assert result.status == "完結"
    assert "インフォボックス" in result.evidence


# 合成フィクスチャ（実データでは未発見）。is_multimedia=False（一次分類がアニメ、
# 「日本のテレビアニメ」で小説にも漫画にも一致しない）かつ本文にMANGA_MARKERSが
# 一切出現しない例。Issue #143のvetoが`_is_novel_primary(extract)`を見ずに
# 「本文にMANGA_MARKERSが無ければ抑止する」だけに単純化された場合、この
# is_multimedia=Falseのケースまで誤って判定不能にしてしまう（ガードの黙って通る
# ミューテーションを検知するために設計した）。
ANIME_PRIMARY_NO_MANGA_MENTION_EXTRACT = (
    "『例のアニメ作品』は、某制作による日本のテレビアニメ。"
    "2020年から2021年まで放送された。"
)


def test_judge_still_upgrades_to_completed_via_infobox_when_not_multimedia_and_no_manga_mention():
    """Issue #143のvetoが`is_novel_primary(extract)`条件を見ていることの担保
    （合成フィクスチャ）。is_multimedia=False（原作小説のメディアミックスではない）
    の記事では、本文中に漫画マーカーが無くても、従来どおりインフォボックス経由で
    完結へ引き上げてよい——このケースはIssue #143が対象とする「原作小説の存在に
    紛れて漫画化の事実を確認できない」状況ではないため。

    このテストが単独で検知できる壊れ方: Issue #143のvetoが`is_novel_primary(extract)`
    条件を見ずに「本文にMANGA_MARKERSが無ければ常に抑止する」よう壊れ、
    is_multimedia=Falseのケースまで誤って判定不能に倒してしまうリグレッション
    （このミューテーションは他のテストでは検知できない——上のKYUUTEI系テストは
    いずれもis_multimedia=Trueのケースしか使っていないため）。
    """
    # 曖昧さ回避表記「(漫画)」経由（trusted=True）で解決させ、_is_about_manga等の
    # 内容チェック（本テストの検証対象ではない）を素通りさせる。
    responses = [
        _response(
            _resolve_response(
                existing=["例のアニメ作品 (漫画)"], missing=["例のアニメ作品"]
            )
        ),
        _response(
            _extract_response(
                "例のアニメ作品 (漫画)", ANIME_PRIMARY_NO_MANGA_MENTION_EXTRACT
            )
        ),
        _response(_wikitext_response(MAIN_BLOCK_COMPLETED)),
    ]

    with patch("comic_checker.wikipedia_client.requests.get", side_effect=responses):
        result = judge("例のアニメ作品")

    assert result.status == "完結"
    assert "インフォボックス" in result.evidence


def test_judge_stays_unknown_when_infobox_main_block_is_ambiguous():
    wikitext_response = _response(
        _wikitext_response(MAIN_BLOCK_ONGOING + "\n\n" + MAIN_BLOCK_COMPLETED)
    )

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=_infobox_probe_responses() + [wikitext_response],
    ):
        result = judge("インフォ実験作品")

    assert result.status == STATUS_UNKNOWN


def test_judge_stays_unknown_when_wikitext_fetch_fails():
    # 回帰テスト: action=parseがエラー応答を返した（_fetch_wikitextがNoneを返す）場合、
    # 例外を発生させず判定不能のまま維持する。
    wikitext_error_response = _response(_wikitext_error_response())

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=_infobox_probe_responses() + [wikitext_error_response],
    ):
        result = judge("インフォ実験作品")

    assert result.status == STATUS_UNKNOWN


# --- Issue #51 (M6-A-2): 着地記事が入力タイトルの作品かを判定する ----------------------
#
# 以下の抽出文はいずれも2026-07-28時点の実記事から採った実文である。カテゴリ3
# （スピンオフ／続編が親作品にリダイレクトする形）の実例と、そこで誤除外してはならない
# 形を固定する。

# `[23]` 彼女、人見知ります が着地する親作品の記事。入力作品はスピンオフとして言及される。
KANOJO_OKARISHIMASU_EXTRACT = (
    "『彼女、お借りします』（かのじょ おかりします）は、宮島礼吏による日本の漫画。"
    "『週刊少年マガジン』（講談社）において、2017年32号から連載中。"
    "略称は「かのかり」。"
    "2020年6月21日から、ヒロインの1人・桜沢墨を主人公としたスピンオフ漫画"
    "『彼女、人見知ります』（かのじょ ひとみしります）が"
    "『マガジンポケット』において連載されている。"
)

# `[47]`（本編・正常系）と `[55]`（スピンオフ・カテゴリ3）が**同じ記事に着地する**。
# 記事側の情報だけでは両者を分けられないので、入力タイトルとの完全一致が決め手になる。
OTONARI_NO_TENSHISAMA_EXTRACT = (
    "『お隣の天使様にいつの間にか駄目人間にされていた件』"
    "（おとなりのてんしさまにいつのまにかだめにんげんにされていたけん）は、"
    "佐伯さんによる日本のライトノベル。"
    "メディアミックスとして、芝田わん作画、優木すず構成によるコミカライズが"
    "2022年1月6日より『マンガUP!』にて連載中。"
    "ぷよによる5.5巻とコミカライズの特装版のショートエピソードを題材としたスピンオフ"
    "『お隣の天使様にいつの間にか駄目人間にされていた件 after the rain』が、"
    "2023年12月7日より同アプリにて連載中。"
)

# `[111]` 精霊の守り人 が着地するシリーズ記事。**部分一致で照合すると誤除外になる形**で、
# 『ジン～アニメ精霊の守り人外伝～』が入力を部分文字列として含み、同じ文に「外伝」がある。
# この行は期待値が`完結`の正常系なので、発動してはならない。
MORIBITO_SERIES_EXTRACT = (
    "守り人シリーズ（もりびとシリーズ）は、上橋菜穂子による異世界ファンタジー小説の"
    "シリーズ作品である。"
    "2007年3月より「月刊少年ガンガン」にて『精霊の守り人』の漫画版が藤原カムイの手で"
    "連載され、全3巻にて完結する。"
    "2008年4月より「ヤングガンガン」にて『ジン～アニメ精霊の守り人外伝～』が連載された。"
)


def test_strip_disambiguation_suffix_removes_editorial_qualifier():
    # Issue #51: 「 (漫画)」はWikipedia編集者の曖昧さ回避表記であって作品名の一部ではない。
    # `_pick_article()`自身が「{変種} (漫画)」をprobeとして組み立て、`_accept_article()`が
    # その接尾辞を「作品記事である」信号として信頼している以上、ゲートでだけ差異として
    # 扱うのは一貫しない。実測では回帰群の7行（陰陽師・日常・タッチ・H2・大奥・ソムリエ・
    # ミスミソウ）がこの形で、除去しないと入力が正しくても常にゲートが開く。
    assert _strip_disambiguation_suffix("陰陽師 (漫画)") == "陰陽師"
    assert _strip_disambiguation_suffix("日常 (漫画)") == "日常"
    # 「(漫画)」固定ではない。回帰群の`風光る`の期待記事名がこの形。
    assert _strip_disambiguation_suffix("風光る (渡辺多恵子の漫画)") == "風光る"
    # 全角括弧も落とす。
    assert _strip_disambiguation_suffix("ソムリエ（漫画）") == "ソムリエ"
    # 接尾辞が無いものは変えない。
    assert _strip_disambiguation_suffix("リコリス・リコイル") == "リコリス・リコイル"
    assert _strip_disambiguation_suffix("守り人シリーズ") == "守り人シリーズ"


def test_mentions_as_derivative_work_detects_category3_rows():
    # Issue #51: カテゴリ3の実データ2件。どちらも親記事のリードで、入力タイトルが
    # 『』に囲まれ、同じ文に派生作品マーカーがある形で言及されている。
    assert _mentions_as_derivative_work(
        KANOJO_OKARISHIMASU_EXTRACT, "彼女、人見知ります"
    ) is True
    assert _mentions_as_derivative_work(
        OTONARI_NO_TENSHISAMA_EXTRACT,
        "お隣の天使様にいつの間にか駄目人間にされていた件　after the rain",
    ) is True


def test_mentions_as_derivative_work_spares_the_parent_work_itself():
    # Issue #51の最大の難所: `[47]`（本編）と`[55]`（スピンオフ）は**同じ記事に着地する**。
    # `[47]`の入力は`[55]`の『』内文字列の前方部分文字列なので、部分一致で照合すると
    # `[47]`も一致してしまう。完全一致にすることで、ゲートに頼らず照合条件の側でも通る。
    assert _mentions_as_derivative_work(
        OTONARI_NO_TENSHISAMA_EXTRACT, "お隣の天使様にいつの間にか駄目人間にされていた件"
    ) is False


def test_mentions_as_derivative_work_does_not_fire_on_series_article():
    # Issue #51: `[111]` 精霊の守り人 → 守り人シリーズ は期待値`完結`の正常系。
    # 部分一致で照合すると『ジン～アニメ精霊の守り人外伝～』（同じ文に「外伝」）に
    # 引っかかって誤除外になる。**ゲートは開いているので、ここで守れないと行が落ちる。**
    assert _mentions_as_derivative_work(
        MORIBITO_SERIES_EXTRACT, "精霊の守り人"
    ) is False


def test_mentions_as_derivative_work_normalizes_ideographic_space():
    # Issue #51: `[55]`の入力は全角スペース(U+3000)を含むが、記事側の『』内は半角スペース。
    # NFKCがU+3000をU+0020に正規化するので一致するが、**生の==では一致せず取り逃がす**。
    raw_input = "お隣の天使様にいつの間にか駄目人間にされていた件　after the rain"
    quoted_in_article = "お隣の天使様にいつの間にか駄目人間にされていた件 after the rain"
    assert raw_input != quoted_in_article  # 正規化しないと一致しないことを明示する
    assert _mentions_as_derivative_work(OTONARI_NO_TENSHISAMA_EXTRACT, raw_input) is True


def test_mentions_as_derivative_work_requires_a_derivative_marker():
    # Issue #51: 『』で言及されているだけでは弾かない。別名・略称は記事主題の言い換えとして
    # 現れるので、マーカーが無い言及は通す（fail-open）。`ONE PIECE`の「『ONE PIECE』
    # （ワンピース）は、」がこの形。
    assert _mentions_as_derivative_work(ONE_PIECE_EXTRACT, "ONE PIECE") is False
    assert _mentions_as_derivative_work(ONE_PIECE_EXTRACT, "ワンピース") is False


def test_mentions_as_derivative_work_falls_open_on_empty_input():
    # Issue #51: #45と同じくfail-open。判定できない入力で除外側に倒してはならない。
    assert _mentions_as_derivative_work("", "彼女、人見知ります") is False
    assert _mentions_as_derivative_work(KANOJO_OKARISHIMASU_EXTRACT, "") is False


# --- Issue #51: 条件A（マーカーが言及を修飾しているか）・条件B（併合記事か） -----------
#
# 敵対群の本調査（作品記事150件・被リダイレクト1,462行）で、7語の候補語彙で掃くと32件が
# 発動し、人手ラベルの結果 (a)＝誤除外が10件出た。以下はその10件の代表形である。

# 併合記事型かつマーカーが『』内にある形。『最遊記外伝』は入力タイトル自身で、
# その中の「外伝」を拾って発動していた（条件A-1で消える）。
# 入力『最遊記』『最遊記RELOAD』『最遊記RELOAD BLAST』は、後ろにある『最遊記外伝』の
# 「外伝」を拾っていた（条件A-2で消える）。リード文が「〜の総称」で併合を宣言している。
SAIYUKI_SERIES_EXTRACT = (
    "『最遊記シリーズ』（さいゆうきシリーズ）は、峰倉かずやによる日本の漫画作品"
    "『最遊記』、『最遊記RELOAD』（さいゆうきリロード）、"
    "『最遊記RELOAD BLAST』（さいゆうきリロード ブラスト）、"
    "『最遊記外伝』（さいゆうきがいでん）、『最遊記異聞』（さいゆうきいぶん）の総称。"
)

# 併合記事型。マーカー「続編」は『バキ』の3字前にあり、**近接条件では救えない**。
# 条件B（「本項ではこれらも併せて解説する」）だけが救える形。
BAKI_EXTRACT = (
    "『グラップラー刃牙』（グラップラーバキ）は、板垣恵介による日本の格闘漫画。"
    "『週刊少年チャンピオン』（秋田書店）に連載された。"
    "続編として『バキ』、『範馬刃牙』、『刃牙道』、『バキ道』、『刃牙らへん』があり"
    "本項ではこれらも併せて解説する。"
)

# 記事名の略称が入力された形。無関係な文にたまたま「前日譚」が同居しているだけで、
# マーカーと『』の距離は92字ある（条件A-3で消える）。併合宣言は無い。
HATHAWAY_EXTRACT = (
    "『機動戦士ガンダム 閃光のハサウェイ』は、富野由悠季による日本の小説。"
    "ガンダムシリーズのうち世界観「宇宙世紀」を描く作品の1つである。"
    "1987年から1988年に劇場アニメ『逆襲のシャア』とほぼ同じストーリーとその前日譚を"
    "含む全3巻の小説も発表されているが、その巻末インタビューで作者の富野は、"
    "同作を「『閃光のハサウェイ』に対する語り直し」と述べている。"
)

_MK7 = ("スピンオフ", "続編", "外伝", "番外編", "前日譚", "派生", "スピンアウト")


def test_declares_merged_coverage_detects_merged_articles():
    # Issue #51: 併合宣言の語彙は150記事の実文から回収した（決め打ちしていない）。
    assert _declares_merged_coverage(BAKI_EXTRACT) is True  # 本項では/併せて解説
    assert _declares_merged_coverage(SAIYUKI_SERIES_EXTRACT) is True  # の総称


def test_declares_merged_coverage_spares_the_target_articles():
    # Issue #51の最大の確認点。`[23]`・`[55]`/`[47]`の着地先が併合記事と判定されると、
    # 本Issueの目的そのものが達成できなくなる。実測でも併合宣言は無い。
    assert _declares_merged_coverage(KANOJO_OKARISHIMASU_EXTRACT) is False
    assert _declares_merged_coverage(OTONARI_NO_TENSHISAMA_EXTRACT) is False
    # `[111]`の着地先。記事名は「〜シリーズ」だが併合宣言は無い＝記事名では判定できない。
    assert _declares_merged_coverage(MORIBITO_SERIES_EXTRACT) is False


def test_condition_a1_ignores_markers_inside_the_quotes():
    # 条件A-1: 『』の中のマーカーは数えない。`最遊記外伝`は入力名自身に「外伝」を含み、
    # 『』外にはマーカーが1つも無い。
    assert _mentions_as_derivative_work(
        SAIYUKI_SERIES_EXTRACT, "最遊記外伝", markers=_MK7, skip_merged_articles=False
    ) is False


def test_condition_a2_requires_the_marker_to_precede_the_quote():
    # 条件A-2: 『最遊記』等は、後ろにある『最遊記外伝』の「外伝」を拾っていた。
    for title in ("最遊記", "最遊記RELOAD", "最遊記RELOAD BLAST"):
        assert _mentions_as_derivative_work(
            SAIYUKI_SERIES_EXTRACT, title, markers=_MK7, skip_merged_articles=False
        ) is False, title


def test_condition_a3_requires_the_marker_to_be_near_the_quote():
    # 条件A-3: 距離92字。MARKER_MAX_DISTANCE(=12)を超えるので修飾とみなさない。
    assert _mentions_as_derivative_work(
        HATHAWAY_EXTRACT, "閃光のハサウェイ", markers=_MK7, skip_merged_articles=False
    ) is False
    # 距離条件を無効化すると、改良前の挙動（誤除外）が再現することを固定する。
    assert _mentions_as_derivative_work(
        HATHAWAY_EXTRACT, "閃光のハサウェイ", markers=_MK7,
        max_distance=None, require_before=False, skip_merged_articles=False
    ) is True


def test_condition_b_is_the_only_thing_that_saves_a_near_marker_in_a_merged_article():
    # `バキ`はマーカーが3字前にあり、条件Aを全て満たしてしまう。条件Bだけが救える。
    assert _mentions_as_derivative_work(
        BAKI_EXTRACT, "バキ", markers=_MK7, skip_merged_articles=False
    ) is True
    assert _mentions_as_derivative_work(BAKI_EXTRACT, "バキ", markers=_MK7) is False


def test_conditions_do_not_break_the_two_target_rows():
    # 条件A・Bを入れても`[23]`・`[55]`は発動し続けること（本Issueの目的）。
    assert _mentions_as_derivative_work(
        KANOJO_OKARISHIMASU_EXTRACT, "彼女、人見知ります", markers=_MK7
    ) is True
    assert _mentions_as_derivative_work(
        OTONARI_NO_TENSHISAMA_EXTRACT,
        "お隣の天使様にいつの間にか駄目人間にされていた件　after the rain",
        markers=_MK7,
    ) is True
    # `[47]`（本編）と`[111]`は引き続き発動しない。
    assert _mentions_as_derivative_work(
        OTONARI_NO_TENSHISAMA_EXTRACT,
        "お隣の天使様にいつの間にか駄目人間にされていた件", markers=_MK7,
    ) is False
    assert _mentions_as_derivative_work(
        MORIBITO_SERIES_EXTRACT, "精霊の守り人", markers=_MK7
    ) is False


def test_judge_drops_a_row_that_lands_on_a_different_work():
    # Issue #51: `彼女、人見知ります`は自分の記事を持たず、Wikipediaのリダイレクトで
    # 親作品『彼女、お借りします』に着地する。従来はそこで親作品の連載状況を根拠に
    # `連載中`と確信を持って誤答していた（M6-D-2/#35 のカテゴリ3、実分布でもD率100%）。
    resolve = _response(
        _resolve_response(
            existing=["彼女、お借りします"],
            missing=["彼女、人見知ります (漫画)"],
            redirects=[("彼女、人見知ります", "彼女、お借りします")],
        )
    )
    extract = _response(
        _extract_response("彼女、お借りします", KANOJO_OKARISHIMASU_EXTRACT)
    )
    empty_search = _response(_search_response([]))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve, extract, empty_search],
    ):
        result = judge("彼女、人見知ります")

    assert result.status == STATUS_NOT_FOUND
    assert result.matched_title is None


def test_judge_keeps_the_parent_work_itself():
    # 同じ記事に着地する`[47]`（本編）は従来どおり採用されること。`[55]`（スピンオフ）と
    # 分ける鍵は入力側にしかないので、ここが壊れると本Issueの変更は使えない。
    title = "お隣の天使様にいつの間にか駄目人間にされていた件"
    resolve = _response(
        _resolve_response(existing=[title], missing=[f"{title} (漫画)"])
    )
    extract = _response(_extract_response(title, OTONARI_NO_TENSHISAMA_EXTRACT))

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[resolve, extract],
    ):
        result = judge(title, use_infobox=False)

    assert result.matched_title == title


def test_different_work_check_is_not_applied_to_the_trusted_path():
    # Issue #45と同じ方針。「〜 (漫画)」は編集者が「作品の記事だ」と明示した表記なので
    # 素通しにする。適用しても得るものが無く、偽陽性（正しい記事を弾く）だけが増える。
    article = ("親作品 (漫画)", KANOJO_OKARISHIMASU_EXTRACT, "https://example.invalid")
    with patch("comic_checker.wikipedia_client._fetch_extract", return_value=article):
        assert _accept_article(
            "親作品 (漫画)", trusted=True, input_title="彼女、人見知ります"
        ) == article
        assert _accept_article(
            "親作品 (漫画)", trusted=False, input_title="彼女、人見知ります"
        ) is None


# --- Issue #56 (M6-B-4): インフォボックスの「終了系が空欄 ⇒ 連載中」に継続の証拠を要求 ---
#
# M6-D-4（Issue #53）の実測: 作品記事1,800件から「地の文が判定不能かつインフォボックスが
# 連載中」の75行を人手判定したところ、**46行（61.3%）が実際には完結していた**。別に取った
# ホールドアウト500記事・21行でも 13行（61.9%）で、2つの独立した標本で率がほぼ一致した。
#
# 空欄は「連載が続いている記録」ではなく「誰も書かなかった」場合と見分けがつかない。
# そこで継続の**積極的な証拠**（`巻数`の`既刊`表記）を要求する。設計は #53 の B-7。

# 2026-07-29 時点の実データから採った`巻数`フィールドの実値。
KIKAN_RECENT = "既刊12巻（2026年2月現在）"          # うしろの正面カムイさん
KIKAN_STALE = "既刊5巻（2017年5月現在）"             # ガンダム Gのレコンギスタ（実際は完結）
KIKAN_NO_DATE = "既刊46巻"                          # やくならマグカップも（連載中）
ZEN_ONLY = "全3巻"                                   # 機動戦士ガンダム外伝（完結）
ZEN_AND_KIKAN = (                                    # コボちゃん（連載中）
    "既刊120巻（蒼鷹社版全60巻+芳文社版既刊61巻）<br />（2026年7月現在）"
)
MULTI_DATE = (                                       # 鬼平犯科帳（連載中）
    "単行本：既刊127巻（2026年4月現在）<br />ワイド版：既刊65巻（2026年4月現在）"
    "<br />文庫版：既刊77巻（2025年4月現在）"
)
WITH_REF_TAG = (                                     # 初めて恋をした日に読む話（連載中）
    "既刊20巻（2026年7月23日現在）<ref name=\"hajikoi\">{{Cite web|和書|"
    "url=https://example.invalid |accessdate=2026-07-23}}</ref>"
)
TODAY = date(2026, 7, 29)  # #53 の測定日。実行日に依存させないため固定して渡す


def test_continuation_evidence_covers_the_four_shapes_from_the_survey():
    # Issue #56: M6-D-4 で見つかった4類型。単純な「既刊があるか」では設計できない。
    # 全N巻だけ → 完結の表現。証拠なし
    assert _has_continuation_evidence(ZEN_ONLY, today=TODAY) is False
    # 既刊だが日付が古い → 更新が止まっている。証拠なし
    assert _has_continuation_evidence(KIKAN_STALE, today=TODAY) is False
    # 全N巻と既刊の同居 → **新しい既刊があるので証拠あり**。否定条件を並べる設計だと
    # ここを誤って弾く（コボちゃんは連載中）。正の証拠を見るからこそ通る。
    assert _has_continuation_evidence(ZEN_AND_KIKAN, today=TODAY) is True
    # 既刊はあるが日付なし → **証拠と認める**（B-7）。日付を書かない編集者が一定数おり、
    # 認めない設計(B-6)だとホールドアウトで副作用が25%に達した。
    assert _has_continuation_evidence(KIKAN_NO_DATE, today=TODAY) is True


def test_continuation_evidence_takes_the_newest_of_several_dates():
    # Issue #56: 版ごとに更新時期が違うだけなので、最新が「最後に更新された時点」を表す。
    # 鬼平犯科帳は 2026/2026/2025 を持つ。最も古い2025を採ると判定が変わる年が出るため、
    # 最新を採ることを固定する。
    assert _has_continuation_evidence(MULTI_DATE, today=date(2029, 1, 1)) is True
    # 最新(2026)からも5年経てば証拠にならない。
    assert _has_continuation_evidence(MULTI_DATE, today=date(2031, 6, 1)) is False


def test_continuation_evidence_reads_dates_through_markup():
    # Issue #56: `<br>` `<ref>` 等のタグを除去せず `(\d{4})年` で走査する。最新を採る
    # 方針なら、ref内の日付を拾っても結論は変わらない。
    assert _has_continuation_evidence(WITH_REF_TAG, today=TODAY) is True


def test_continuation_evidence_does_not_depend_on_the_run_date():
    # Issue #56: 「5年以内」は実行時点に依存するので、基準日を注入できないと
    # 2026年に「2022年は新しい」と書いたテストが2028年に落ちる。
    volumes = "既刊3巻（2022年5月現在）"
    assert _has_continuation_evidence(volumes, today=date(2026, 1, 1)) is True
    assert _has_continuation_evidence(volumes, today=date(2028, 1, 1)) is False


def test_continuation_evidence_falls_closed_without_a_field():
    # Issue #56: `巻数`フィールド自体が無い形。証拠が取れないので判定不能に倒す。
    # ⚠ 実測では連載中の作品（`一人之下`）もこの形を取りうる。合算96行での副作用1件は
    # これで、日付の扱いでは対処できない（docs/known_limitations.md 参照）。
    assert _has_continuation_evidence(None, today=TODAY) is False
    assert _has_continuation_evidence("", today=TODAY) is False


def test_judge_via_infobox_requires_continuation_evidence():
    # Issue #56: 終了系が空欄でも、継続の証拠が無ければ連載中と断定しない。
    wikitext_stale = (
        # 本編ブロックは`タイトル`フィールドを持たないもの（_find_main_manga_block）。
        "{{Infobox animanga/Manga\n|巻数 = " + KIKAN_STALE
        + "\n|終了号 = \n|終了日 = \n}}"
    )
    status, _evidence = _judge_via_infobox(wikitext_stale, today=TODAY)
    assert status is None

    wikitext_recent = (
        "{{Infobox animanga/Manga\n|巻数 = " + KIKAN_RECENT
        + "\n|終了号 = \n|終了日 = \n}}"
    )
    status, evidence = _judge_via_infobox(wikitext_recent, today=TODAY)
    assert status == "連載中"
    assert "既刊" in evidence


def test_judge_via_infobox_still_reports_completion_from_a_filled_field():
    # Issue #56: 完結方向は変えていない。終了系に値があれば継続の証拠を見るまでもない。
    wikitext = (
        "{{Infobox animanga/Manga\n|巻数 = " + ZEN_ONLY
        + "\n|終了号 = 2020年12号\n}}"
    )
    status, evidence = _judge_via_infobox(wikitext, today=TODAY)
    assert status == "完結"
    assert "終了号" in evidence


def test_infobox_decided_rows_keep_their_continuation_evidence():
    # Issue #56: M6-D-3 の INFOBOX_DECIDED 6行。実運用でこの経路が決めている行で、
    # 6行とも期待値は`連載中`。#53 の実測では B-7 で発動0/6件だった。
    # 巻数の実値は 2026-07-29 に取得したもの。
    for volumes in (
        "既刊12巻（2026年2月現在）",   # [13] うしろの正面カムイさん
        "既刊15巻（2026年4月現在）",   # [19] てんぷる
        "既刊33巻（2026年6月現在）",   # [28] カッコウの許嫁
        "既刊15巻（2026年7月現在）",   # [52] 月曜日のたわわ
        "既刊8巻（2026年1月現在）",    # [57] リコリス・リコイル
        "既刊21巻（2026年6月現在）",   # [72] 魔都精兵のスレイブ
    ):
        assert _has_continuation_evidence(volumes, today=TODAY) is True, volumes


# --- Issue #40: Wikipedia API 利用の作法（間隔・リトライ・User-Agent） -----------------
#
# 本番（CLI・GUI）は`_api_get`にも`main.py`の行ループにも待機が無く、1行あたり2〜4
# リクエストを間隔ゼロで連射していた。M6-A-2（#51）の調査中に実際に429を踏んでいる。
# 調査スクリプト側は自前で待機を持っていたが、間隔の値も待機の単位もばらばらだった
# （measure系は「1行ごと」、survey系は「1リクエストごと」）。`_api_get`に一本化する。


def _ok_response(payload=None):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload if payload is not None else {"query": {}}
    return response


def _throttled_get(responses):
    """`requests.get`と`time.sleep`を差し替えて、待機の呼ばれ方を記録する。"""
    sleeps = []
    patch_get = patch(
        "comic_checker.wikipedia_client.requests.get", side_effect=responses
    )
    patch_sleep = patch(
        "comic_checker.wikipedia_client.time.sleep", side_effect=sleeps.append
    )
    return sleeps, patch_get, patch_sleep


@pytest.mark.real_wait_settings
def test_api_get_waits_once_before_each_request():
    # Issue #40: 待機は**1リクエストごと**に入る。1行が2〜4リクエストを出すので、
    # 「1行ごと」に待つ従来のmeasureスクリプトではバーストが残っていた。
    # **期待値は定数ではなくリテラルで書く。** 定数を両辺に使うと、値を変えても期待値が
    # 一緒に動いてしまい、変更を検出できない（`API_MAX_ATTEMPTS`で実際にそうなっていた）。
    # 1.0秒という値は#40で意図して選んだもの（速い側に倒すと429で実行全体が落ちるのに対し、
    # 遅い側は待つだけなので fail-safe）なので、黙って変わらないように固定する。
    assert API_REQUEST_INTERVAL == 1.0, "間隔を変えるなら、このテストの期待値も意図して更新すること"

    sleeps, patch_get, patch_sleep = _throttled_get([_ok_response()])
    with patch_get, patch_sleep:
        _api_get({"action": "query"})
    assert sleeps == [1.0]

    sleeps, patch_get, patch_sleep = _throttled_get([_ok_response(), _ok_response()])
    with patch_get, patch_sleep:
        _api_get({"action": "query"})
        _api_get({"action": "query"})
    assert sleeps == [1.0, 1.0]


@pytest.mark.real_wait_settings
def test_api_get_backs_off_exponentially_on_429():
    # Issue #40: 429は待って再試行する。待機はリクエスト間隔とは別に、
    # 試行回数に比例して伸ばす（5秒・10秒・15秒…）。
    too_many = MagicMock()
    too_many.status_code = 429
    sleeps, patch_get, patch_sleep = _throttled_get([too_many, too_many, _ok_response()])
    with patch_get, patch_sleep:
        _api_get({"action": "query"})
    # 各試行の前に間隔、429のたびにバックオフが入る。
    assert sleeps == [
        API_REQUEST_INTERVAL,
        API_RETRY_BACKOFF_SECONDS * 1,
        API_REQUEST_INTERVAL,
        API_RETRY_BACKOFF_SECONDS * 2,
        API_REQUEST_INTERVAL,
    ]


@pytest.mark.real_wait_settings
def test_api_get_gives_up_after_six_attempts():
    # Issue #40: 無限に粘らない。上限まで429が続いたらHTTPErrorを投げて呼び出し側に返す
    # （測定スクリプトはここで止まって、何回目で諦めたかを報告できる）。
    #
    # **期待値は定数ではなくリテラルで書く。** `API_MAX_ATTEMPTS`を両辺に使うと、定数を
    # 変えてもテストの期待値が一緒に動いてしまい、上限の変更を検出できない
    # （実際に6→3に変えても落ちない空振りテストになっていた）。
    assert API_MAX_ATTEMPTS == 6, "上限を変えるなら、このテストの期待値も意図して更新すること"
    too_many = MagicMock()
    too_many.status_code = 429
    too_many.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "429 Client Error", response=too_many
    )
    sleeps, patch_get, patch_sleep = _throttled_get([too_many] * 6)
    with patch_get, patch_sleep:
        with pytest.raises(requests.exceptions.HTTPError):
            _api_get({"action": "query"})
    # 6回試行し、そのうち5回は429で待ってから再試行している。
    assert sleeps.count(API_REQUEST_INTERVAL) == 6
    assert sleeps.count(API_RETRY_BACKOFF_SECONDS * 5) == 1


@pytest.mark.real_wait_settings
def test_api_get_does_not_retry_other_http_errors():
    # Issue #40: 429以外（403・404等）は待っても直らないので即座に投げる。
    # #51で自前のrequests.getを書いて403を踏んだが、原因はUser-Agent未送信であり、
    # リトライで解決する種類のものではなかった。
    forbidden = MagicMock()
    forbidden.status_code = 403
    forbidden.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "403 Client Error", response=forbidden
    )
    sleeps, patch_get, patch_sleep = _throttled_get([forbidden])
    with patch_get, patch_sleep:
        with pytest.raises(requests.exceptions.HTTPError):
            _api_get({"action": "query"})
    assert sleeps == [API_REQUEST_INTERVAL]


@pytest.mark.real_wait_settings
def test_api_get_sends_a_contactable_user_agent():
    # Issue #40 §1: WikimediaのUser-Agentポリシーは「連絡可能なURLまたはメールアドレス」を
    # 求めている。プレースホルダの`https://github.com/`は連絡先として機能していなかった。
    assert "github.com/giant-shrimp/comic_checker" in USER_AGENT
    assert "https://github.com/;" not in USER_AGENT

    sleeps, patch_get, patch_sleep = _throttled_get([_ok_response()])
    with patch_get as mocked, patch_sleep:
        _api_get({"action": "query"})
    assert mocked.call_args.kwargs["headers"]["User-Agent"] == USER_AGENT


def test_callers_that_skip_api_get_do_not_wait():
    # Issue #40: 待機は`_api_get`の中にしかない。ディスクキャッシュを持つ調査スクリプトは
    # ヒット時に`_api_get`を呼ばないので、待機も発生しない。ここが崩れると、
    # キャッシュがあるのに再実行が数十分かかることになり、調査が実用不能になる。
    sleeps, _patch_get, patch_sleep = _throttled_get([])
    with patch_sleep:
        pass  # `_api_get`を呼ばなければ待機は1度も起きない
    assert sleeps == []


def test_api_get_has_no_statement_after_the_retry_loop():
    """Issue #121: `_api_get`の`for`ループより後ろに文を置かない。

    ループ内に`break`が無く、最後の反復では`attempt < API_MAX_ATTEMPTS - 1`が偽に
    なるため`continue`も発火しない。したがって最後の反復は必ず例外送出か`return`で
    終わり、ループが正常終了して外側の行へ抜ける経路は存在しない。ループ後に置いた
    文（かつて在った`response.raise_for_status()`）は到達不能なデッドコードになる。
    再発を防ぐため、関数本体の最後の文が`for`ループそのものであることを検証する。

    行番号もソース文字列もハードコードせず、関数名で`_api_get`の定義を探索する。
    """
    source = Path(wikipedia_client.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_api_get"
    )
    assert isinstance(func.body[-1], ast.For), (
        "_api_get の for ループより後ろに文がある。"
        "ループ後の文は到達不能なので置かないこと（Issue #121）"
    )

# --- Issue #62: 定数を期待値と入力の両方に使うと、定数を変えてもテストが落ちない ---------
#
# #40 の棚卸しで本番の定数8個を変異させたところ、5個が1件も落ちなかった。うち
# `API_MAX_ATTEMPTS` と `API_REQUEST_INTERVAL` は #40 で直した。残る3つをここで固定する。
#
# **値を固定する目的は「この値が正しい」と主張することではない。** 変えるときに意図的な
# 更新を強制することである。根拠は各アサートのコメントに書いてある。


def test_marker_max_distance_is_pinned():
    # Issue #51 で実測から選んだ値。**この値を変えるなら、同じ分布を測り直すこと。**
    #
    # 出所: 発動32件の距離分布で、(b)（検出すべき）は 1〜11 に密集し、併合宣言を持たない
    # (a)（誤除外）は `閃光のハサウェイ` の92だけだった。
    #
    # ⚠ **12〜91 のどの値でもラベル済みデータ上の結果は同一である。** 中間距離の (a)
    # （15・16・27・48）は全て併合記事で、条件B（`_declares_merged_coverage`）が先に
    # 止めているため。距離条件が単独で守っているのは距離92の1件のみ。
    #
    # したがって**挙動を固定するテストではこの定数の変更を検出できない**（12→5 も 12→40 も
    # 結果が変わらない）。境界のフィクスチャを合成して埋める案は採らなかった ―― 距離13の
    # (a) 相当は実データに存在せず、存在しない形を固定すると根拠のない挙動を固めることに
    # なる（#53 で踏んだ「分布から読めない型」と同じ構造）。値の固定だけを行う。
    assert MARKER_MAX_DISTANCE == 12


def test_status_strings_are_pinned():
    # Excel の状況列にそのまま書き戻される文字列なので、変わると利用者の出力が変わる。
    # `tests/test_row_counts.py` 等がリテラルをワークブックの中身として書いているが、
    # 定数と突き合わせてはいないため、定数側を変えても検出できなかった（#62）。
    assert STATUS_UNKNOWN == "判定不能"
    assert STATUS_NOT_FOUND == "記事なし"


# --- Issue #154（案B）: _has_ongoing_signal() へのSPINOFF_MARKERS除外 ---
#
# docs/code_defects_2026-08/prereg_planb_safety_verification.md・
# docs/code_defects_2026-08/planb_verification_result.md・
# docs/code_defects_2026-08/planb_mutation_result.mdを参照。


def test_has_ongoing_signal_excludes_each_spinoff_marker_individually():
    """SPINOFF_MARKERSの5要素それぞれについて、その要素タグ付きの文が
    _has_ongoing_signal()の走査から個別に除外されることを確認する
    （案Bの合成フィクスチャによるミューテーションテスト、
    docs/code_defects_2026-08/planb_mutation_result.md参照）。

    5要素を1つの文にまとめず個別にテストすることで、CLAUDE.mdが定める
    「複数ガードが同じ値を返す場合、一つを除去しても出力が変わらない」問題
    （1要素が機能しなくても他要素が拾ってしまい合格に見える問題）を避ける。
    """
    fixtures = [
        ("続編", "続編『二代目主人公』が『月刊なんとか』にて連載中。"),
        ("番外編", "番外編『裏エピソード』が『月刊なんとか』にて連載中。"),
        ("スピンオフ", "スピンオフ『外伝物語』が『月刊なんとか』にて連載中。"),
        ("外伝", "外伝『裏話』が『月刊なんとか』にて連載中。"),
        ("次世代編", "次世代編『新世代』が『月刊なんとか』にて連載中。"),
    ]
    for marker, sentence in fixtures:
        assert _has_ongoing_signal(sentence) is False, (
            f"「{marker}」タグ付き文がhas_ongoing_signal()の走査から除外されなかった"
        )


def test_has_ongoing_signal_does_not_exclude_unrelated_words():
    """負のコントロール: SPINOFF_MARKERSに無い語（元のマーカーと意味は近いが
    部分文字列としても重ならない語）では除外が働かないことを確認する。
    除外判定がSPINOFF_MARKERSの5語だけに反応しており、無関係な近い語を
    巻き込んでいないことの担保（除外判定の粒度の確認、
    docs/code_defects_2026-08/planb_mutation_result.md「追加した負のコントロールの
    設計」参照）。
    """
    fixtures = [
        "リメイク版『新装版』が『月刊なんとか』にて連載中。",
        "後編『新装版』が『月刊なんとか』にて連載中。",
        "特別編『新装版』が『月刊なんとか』にて連載中。",
        "スピンアウト『新装版』が『月刊なんとか』にて連載中。",
        "外典『新装版』が『月刊なんとか』にて連載中。",
        "新世代作品『新装版』が『月刊なんとか』にて連載中。",
    ]
    for sentence in fixtures:
        assert _has_ongoing_signal(sentence) is True, f"無関係な語が誤って除外された: {sentence}"


# Issue #154（作業98-B抜き取り測定の延長、案Bの安全性検証で発見、実データ）。
# 『陰陽師』本編は`終了号 = [[2005年]]7月号`と実際に完結しているが、続編
# 『陰陽師 玉手匣』についての「連載されている」という文（`_has_ongoing_signal()`が
# SPINOFF_MARKERSを経由せず抽出全体を走査していたため拾われていた）が、
# インフォボックスの「完結」判定をvetoしていた（`judge()`のIssue #30由来のveto）。
# 案B適用後、この続編文が除外されるためvetoが発火しなくなり、インフォボックス経由で
# 正しく「完結」に到達する。
ONMYOJI_EXTRACT_FULL = (
    "『陰陽師』（おんみょうじ）は、夢枕獏の小説『陰陽師』を原作とする岡野玲子の漫画。"
    "1993年から2005年に、『コミックバーガー』『コミックバーズ』（いずれもスコラ）、"
    "『月刊メロディ』（白泉社）で連載された。2006年、第37回星雲賞コミック部門を"
    "受賞している。2019年4月時点でシリーズ累計発行部数は600万部を突破している。\n"
    "続編に『陰陽師 玉手匣』がある。\n"
    "なお、夢枕の同小説の漫画化作品には他に、睦月ムンクによる『陰陽師 瀧夜叉姫』と"
    "伊藤勢による『瀧夜叉姫 陰陽師絵草子』がある（小説の記事を参照）。\n\n\n"
    "== 概要 ==\n"
    "『コミックバーガー』1993年7月号から1996年4月号、『コミックバーズ』1996年7月号"
    "から1999年5月号、『月刊メロディ』1999年8月号から2005年5月号に連載された。"
    "単行本は全13巻が白泉社（JETS COMICS）から発行された。\n"
    "なお、続編の『陰陽師 玉手匣』は『MELODY』2011年2月号から連載されている。\n"
)

# 実際のWikipedia記事『陰陽師 (漫画)』のインフォボックスをそのまま書き写した
# （regression_corpus_2026-08/regression_corpus_wikitext.jsonの保存済みスナップショット
# より、2026-08-15取得時点の値）。
ONMYOJI_REAL_WIKITEXT = (
    "{{Infobox animanga/Manga\n"
    "|作者= [[夢枕獏]]（原作）\n"
    "|作画= [[岡野玲子]]\n"
    "|出版社= [[スコラ]]、[[白泉社]]\n"
    "|掲載誌= [[月刊バーズ|コミックバーガー]]<br />→[[月刊バーズ|コミックバーズ]]<br "
    "/>→[[MELODY (雑誌)|月刊メロディ]]\n"
    "|レーベル= [[ジェッツコミックス|JETS COMICS]]\n"
    "|開始号= [[1993年]]7月号 - [[1996年]]5月号<br />（コミックバーガー）<br "
    "/>1996年7月号 - [[1999年]]5月号<br />（コミックバーズ）<br />1999年8月号\n"
    "|終了号= [[2005年]]7月号<br />（月刊メロディ）\n"
    "|開始日= 1993年[[5月26日]]\n"
    "|終了日= 2005年[[5月28日]]\n"
    "|巻数= 全13巻\n"
    "|話数=\n"
    "|その他= \n"
    "}}"
)


def test_judge_onmyoji_reaches_completed_via_infobox_after_zokuhen_exclusion():
    """回帰テスト（実データ、Issue #154）: 陰陽師は案B適用後、`_judge_extract`単体は
    判定不能のままだが、`judge()`全体ではインフォボックスveto経由で「完結」に到達する。

    バーテンダー à Tokyo（`test_judge_extract_excludes_zokuhen_sentence_bartender_a_tokyo`
    参照）とは異なり、本編自身の決着文候補（「…で連載された。」）が
    `is_multimedia=True`かつMANGA_MARKERSを含まないためmultimedia gateで
    決着せず、`_judge_extract`単体では判定不能のまま残る。したがって
    `judge()`全体（インフォボックス・フォールバックを含む）でしか変化を
    観測できず、この回帰テストは`_judge_extract`直呼びではなく`judge()`経由で書く
    （既存のM6-B-3関連のインフォボックスveto回帰テスト、
    `test_judge_does_not_let_infobox_declare_completed_against_prose_ongoing_signal`
    等と同じ形式）。

    このテストが単独で検知できる壊れ方: `_has_ongoing_signal()`のSPINOFF_MARKERS
    除外が外れる（またはそもそも実装されない）リグレッション。その場合、続編文の
    「連載されている」を拾ってインフォボックスの「完結」判定がvetoされ続け、
    判定不能に戻る。
    """
    responses = [
        _response(_resolve_response(existing=["陰陽師 (漫画)"], missing=["陰陽師"])),
        _response(_extract_response("陰陽師 (漫画)", ONMYOJI_EXTRACT_FULL)),
        _response(_wikitext_response(ONMYOJI_REAL_WIKITEXT)),
    ]

    with patch("comic_checker.wikipedia_client.requests.get", side_effect=responses):
        result = judge("陰陽師")

    assert result.status == "完結"
    assert result.evidence == "インフォボックス: 終了号 = [[2005年]]7月号<br />（月刊メロディ）"
