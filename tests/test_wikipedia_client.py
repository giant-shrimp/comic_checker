from unittest.mock import MagicMock, patch

from comic_checker.wikipedia_client import (
    COMPLETED_STRONG_RE,
    MANGA_INFOBOX_MARKER,
    STATUS_NOT_FOUND,
    STATUS_UNKNOWN,
    WikipediaJudgment,
    _extract_braced_blocks,
    _has_ongoing_signal,
    _judge_extract,
    _judge_via_infobox,
    _search_queries,
    _strip_annotations,
    _strip_trailing_note,
    _title_variants,
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

# M6-B-3対応の合成フィクスチャ。本編の文が連載中と完結の両シグナルを含んで曖昧扱いで
# スキップされたあと、*別作品*の連載終了に言及した文を掴んでしまうパターン。
# 元になった実例は「サタノファニ」で、本編の「2017年15号から2023年34号まで連載され、
# その後『ヤンマガWeb』に移籍し、同年9月6日より連載中。」がスキップされた結果、
# 概要節の「作者が…『DEATHTOPIA』の連載終了から4か月後に…」を採用していた。
# 別作品名を主語にした文はSPINOFF_MARKERSでは弾けない（番外編でも外伝でもない）ため、
# 走査範囲全体の継続シグナルによる無効化でしか止められない。
# なお、このケースで期待するのは「連載中」ではなく「判定不能」である。本編の文が
# 曖昧である事実は変わらず、fail-closedに倒すのが正しい（Issue #8以来の方針）。
OTHER_WORK_COMPLETION_EXTRACT = (
    "『例の曖昧作品』は、某作者による日本の漫画作品。"
    "『週刊サンプルA』（サンプル社）にて、2017年15号から2023年34号まで連載され、"
    "その後『サンプルWeb』に移籍し、同年9月6日より連載中。"
    "作者が『サンプルB』（サンプル社）で連載していた『別の過去作』の連載終了から"
    "4か月後に『週刊サンプルA』へ移籍し、連載が開始された。"
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


def test_strong_completion_is_not_vetoed_by_ongoing_elsewhere():
    # M6-B-3の無効化が弱シグナル限定であることの担保（Issue #8以来の方針）。
    # 「完結」（強シグナル）は、走査範囲内に別の連載中シグナルがあっても無効化しない。
    # 作品名自体に「完結」を含めるとタイトルの文がCOMPLETED_STRONG_REに一致してしまい、
    # 本来検査したい文とは別の文が根拠に採用されるため、無関係な作品名にしている。
    extract = (
        "『例の終了作品』は、某作者による日本の漫画作品。"
        "本編は2020年に完結した。"
        "スピンオフ『例の終了作品外伝』は現在も連載中。"
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
    # フィクスチャのコメントに書いたとおり、この記事に着地する行（こさめちゃん・
    # 横須賀こずえ）は本Issueの修正後も別の理由で誤答のままなので、ステータスは固定せず、
    # 居住地の文が連載シグナルとして扱われないことだけを検証する。
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
    # フィクスチャのコメントに書いたとおり、この行は本Issueの修正後も記事選定側の理由で
    # 誤答のままなので、ステータスは固定せず作風の文が根拠にならないことだけを検証する。
    _, evidence = _judge_extract(AUTHOR_ARTICLE_STYLE_EXTRACT)
    assert evidence is None or "1コママンガ" not in evidence


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
MAIN_BLOCK_ONGOING = _manga_infobox_block(
    [
        ("作者", "[[某作者]]"),
        ("出版社", "[[集英社]]"),
        ("開始号", "2015年1号"),
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
    "|終了号 = \n"
    "|終了日 = \n"
    "}}"
)


def test_judge_via_infobox_main_block_is_ongoing_when_end_fields_are_empty():
    # HUNTER×HUNTER形: 本編ブロックの終了号/終了日が空欄なら連載中。
    wikitext = MAIN_BLOCK_ONGOING + "\n\n" + SPINOFF_BLOCK
    status, evidence = _judge_via_infobox(wikitext)
    assert status == "連載中"
    assert "インフォボックス" in evidence


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
        result = judge("インフォ実験作品")

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
    ambiguous_extract = (
        "『例の曖昧作品』は、某作者による日本の漫画作品。"
        "『週刊サンプルA』にて2017年から2023年まで連載され、その後移籍し、同年より連載中。"
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
