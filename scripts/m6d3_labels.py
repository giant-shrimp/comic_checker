"""M6-D-3（Issue #47）拡張群の期待値ラベル定義。

**このファイルがラベルの正である。** Issue 本文の表は測定時点のスナップショットにすぎない
（Issue はコードと一緒に diff できないため）。ラベルを修正した場合、その diff がレビュー
対象になる。

## 母集団の性質（結果を読む前に必ず読むこと）

ここに並ぶ72タイトルは、M6-E-1（Issue #30）で使った実運用 Excel（73行）から、
#35 の57件と重複する1件（`一緒に暮らしていいですか?`）を NFKC 正規化後の完全一致で
除外した**全数**である。標本抽出ではない。

**全件が実際に発売されたコミックである**（e-hon https://www.e-hon.ne.jp/bec/EB/Top で
確認済み）。**入力ミスや架空のタイトルは1件も含まれない。** したがって:

- 期待値 `記事なし` は「**Wikipedia に記事が無い**」という意味であり、「作品が存在しない」
  でも「入力が誤っている」でもない。#35 §0 の期待値定義（測るのは
  「Wikipedia の記事から連載状況を読み取れるか」であって作品の実態ではない）と整合する。
- **`記事なし` が 32/72 = 44.4% を占めるのはツールの失敗ではなく母集団の性質である。**
  結果を読む人が「入力データが汚い」と誤読しないこと。
- 実運用の入力には Web連載・成年向け・レーベル系など、**Wikipedia に記事が作られにくい
  作品が相当数含まれる**。#35 のサンプル（全件で記事が実在する前提で構成）とは
  この点で決定的に性質が違う。

**実運用 Excel 本体はコミットしない。** リポジトリに入るのはタイトル文字列とラベルのみ。

## 期待値の定義

Issue #47 の「偽陰性の判定基準」に従う。期待記事の**「リード＋最初の `==` セクション」
および `{{Infobox animanga/Manga}}` の終了系フィールド**を人手で読んで決めた（新定義）。
過去のツール出力は一切参照していない。

インフォボックスを含めるのは #35 からの定義変更である（#35 §4 の申し送り）。実装は既定で
インフォボックス補助経路（#12）も使うため、地の文だけで期待値を決めると実装が正しいのに
ラベル側が誤る。

## 列の意味

- `title`        : 入力タイトル（**原文のまま**。表記ゆれの再現に必要なので正規化しない）
- `expected_page`: 期待記事名。`None` は期待値が `記事なし` であることを意味する
- `expected`     : 期待ステータス（`連載中` / `完結` / `判定不能` / `記事なし`）
- `exists`       : 記事実在（`○` / `△` / `×`）。定義は下記
- `merged_into`  : `△` のときの統合先の種別。それ以外は `None`
- `category`     : 記事選定の結果として観測された現象（#35 のカテゴリ体系を流用）
- `marks`        : 判定経路マーク（複数可）。#47 完了条件の内訳を組むのに使う

### 記事実在（#35 の定義を流用）

- `○` = 入力作品専用の記事が実在（31件）
- `△` = **漫画版の独立記事が無く、原作・シリーズ・アニメ記事に統合**されている（9件）
- `×` = 作品の記事が存在しない（32件）

`△` の9件は「入力作品の判断材料が、入力作品専用でない記事に統合されている」点で共通するが、
**統合先の性質が3種に分かれる**ので `merged_into` で区別する（測定後に `△` の行が
どう振る舞ったかを種別ごとに見られるようにするため）。

**所見: 実分布では `△` が 9/72 = 12.5% を占める。** #35 の母集団にはこの規模では
存在しなかった（#35 のカテゴリ1に △ が4件あるが、そちらは意図的に構成したもの）。
メディアミックス作品の判定（#41 の対象）が実運用でどれだけ効くかを示す数字である。

### 番号

`no` は 1〜72 で固定。**振り直さないこと。** 1〜60 は当初の60件抽出時の番号をそのまま
維持しており（確定済みラベルの番号がずれるのを避けるため）、61〜72 は全数調査への変更時に
末尾へ追加した分である。経緯は Issue #47 を参照。
"""

ONGOING = "連載中"
COMPLETED = "完結"
UNKNOWN = "判定不能"
NOT_FOUND = "記事なし"

# merged_into の値
MERGED_NOVEL = "原作小説/LN"
MERGED_ILLUSTRATION = "イラスト群"
MERGED_ANIME = "アニメ記事"

# category の値
CAT_NORMAL = "正常系"
CAT_ABSENT = "記事なし（不在）"
CAT_AUTHOR = "2（作者記事）"
CAT_PARENT = "3（親作品）"

# --- 判定経路マーク --------------------------------------------------------------------
#
# 測定後、このマークだけから #47 完了条件の「偽陰性がどの判定経路で落ちているか」の
# 内訳表を機械的に組めることを要件とする。
#
#   M-1  メディアミックス型（一次分類が小説/LN）        → 偽陰性 / #41 の対象
#   M-1a  └ 下位形: 原作と漫画で連載状況が食い違う       → 偽陰性＋誤答 / #41 で最重要
#   M-2  リードに`連載中`/`連載されている`の語形が無い   → 偽陰性 / 語彙・走査範囲
#   M-2a  └ 下位形: リードに無く最初の==セクションのみ   → 偽陰性 / 走査範囲の設計判断を直接測る
#   M-3  カテゴリ3の下位形（親記事に入力作品の連載文）   → 誤答（期待が記事なしなので分母外）
#   M-4  リード内に*別作品*の連載終了が同居             → 誤答 / #38 の対象
#   M-5  インフォボックス終了系が非空欄だが終了でない   → 誤答 / #12 の経路
#   M-6  走査範囲内に #37 で除外した複合語が実在        → 回帰確認（#37）
#   M-7  休載同居型（語形はあるが打ち消しが同居）       → 誤答または偽陰性 / シグナル優先順位
#   M-8  地の文（走査範囲）に判定材料が無い             → インフォボックス経路への依存（#12）
#   M-9  類似タイトルを完全一致の裏付け無しで不採用     → 回帰確認（#8・#9 の fail-closed）
#   移籍  掲載誌の移籍が記述されている                  → 回帰確認（#8・#30）
M1 = "M-1"
M1A = "M-1a"
M2 = "M-2"
M2A = "M-2a"
M3 = "M-3"
M4 = "M-4"
M5 = "M-5"
M6 = "M-6"
M7 = "M-7"
M8 = "M-8"
M9 = "M-9"
TRANSFER = "移籍"

# M-8 の定義は測定後に見直した（Issue #47）。当初は「判定に必要な情報が走査範囲に存在しない」
# ＝「分母外・分類Aの正解」としていたが、[57] ではインフォボックスに情報があり、そこで
# `連載中` が決着した。**走査範囲（＝`_lead_and_first_section()` が返す地の文）に判定材料が
# 無いのは事実**なので、マーク自体は [57] に付けたまま残し、効く指標だけを
# 「インフォボックス経路への依存」に改めた。
#
# この見直しで M-2 と M-8 の関係が明確になった:
#   M-2（語形は無いが連載の記述はある）= [13][19][28][52][72]
#   M-8（記述自体が無い）              = [57]
#   → **和集合が、インフォボックス経路で決着した6行と完全に一致する**（6/42 = 14.3%）。
# つまり M-2・M-8 が全件正答したのは語彙が対応したからではなく、インフォボックス経路が
# 救っていたためである。当初の分析（「M-2 は他の経路で救済されていた」）の具体化にあたる。
INFOBOX_DECIDED = (13, 19, 28, 52, 57, 72)


class Label:
    __slots__ = ("no", "title", "expected_page", "expected", "exists", "merged_into",
                 "category", "marks")

    def __init__(self, no, title, expected_page, expected, exists, merged_into,
                 category, marks=()):
        self.no = no
        self.title = title
        self.expected_page = expected_page
        self.expected = expected
        self.exists = exists
        self.merged_into = merged_into
        self.category = category
        self.marks = tuple(marks)


_ = None  # merged_into / expected_page の「なし」を短く書くための別名

LABELS = (
    Label(1, "わたしのために脱ぎなさいっ！", "わたしのために脱ぎなさいっ!", ONGOING, "○", _, CAT_NORMAL),
    Label(2, "私の百合はお仕事です！", "私の百合はお仕事です!", ONGOING, "○", _, CAT_NORMAL),
    Label(3, "異世界迷宮でハーレムを", "異世界迷宮でハーレムを", ONGOING, "△", MERGED_NOVEL, CAT_NORMAL, (M1,)),
    Label(4, "はじめてのギャル", "はじめてのギャル", ONGOING, "○", _, CAT_NORMAL),
    Label(5, "わたしの幸せな結婚(特装版がない場合通常版）", "わたしの幸せな結婚", ONGOING, "△", MERGED_NOVEL, CAT_NORMAL, (M1,)),
    Label(6, "私のＨな履歴書みてください", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(7, "終わりのハテミは繁殖したい　③～定期", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(8, "姫騎士がクラスメート！　ＴＨＥ　ＣＯＭＩＣ", "姫騎士がクラスメート!", UNKNOWN, "△", MERGED_NOVEL, CAT_NORMAL),
    Label(9, "ふたりスイッチ", _, NOT_FOUND, "×", _, CAT_AUTHOR),
    Label(10, "ギャルせん", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(11, "彼女、お借りします", "彼女、お借りします", ONGOING, "○", _, CAT_NORMAL),
    Label(12, "恥じらう君が見たいんだ", "恥じらう君が見たいんだ", ONGOING, "○", _, CAT_NORMAL),
    Label(13, "うしろの正面カムイさん", "うしろの正面カムイさん", ONGOING, "○", _, CAT_NORMAL, (M2,)),
    Label(14, "すりこみっ！", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(15, "よあそびぐらしっ！", "よあそびぐらしっ!", ONGOING, "○", _, CAT_NORMAL),
    Label(16, "やっぱ人間やめて正解だわ", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(17, "黒月のイェルクナハト", "黒月のイェルクナハト", ONGOING, "○", _, CAT_NORMAL),
    Label(18, "さわらないで小手指くん", "さわらないで小手指くん", ONGOING, "○", _, CAT_NORMAL),
    Label(19, "てんぷる", "てんぷる", ONGOING, "○", _, CAT_NORMAL, (M2,)),
    Label(20, "異世界NTR", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(21, "あの島の海音荘", "あの島の海音荘", ONGOING, "○", _, CAT_NORMAL, (M4,)),
    Label(22, "ヤンキーＪＫクズハナちゃん", "ヤンキーJKクズハナちゃん", ONGOING, "○", _, CAT_NORMAL),
    Label(23, "彼女、人見知ります", _, NOT_FOUND, "×", _, CAT_PARENT, (M3,)),
    Label(24, "軍神のタクト", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(25, "お願い、脱がシて。", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(26, "ゆめねこねくと", "ゆめねこねくと", ONGOING, "○", _, CAT_NORMAL),
    Label(27, "柊さんちの吸血事情", "柊さんちの吸血事情", ONGOING, "○", _, CAT_NORMAL),
    Label(28, "カッコウの許嫁　(特装版ない場合通常版)", "カッコウの許嫁", ONGOING, "○", _, CAT_NORMAL, (M2,)),
    Label(29, "真夜中ハートチューン", "真夜中ハートチューン", ONGOING, "○", _, CAT_NORMAL),
    Label(30, "あらくさ忍法帖", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(31, "黒岩メダカに私の可愛いが通じない", "黒岩メダカに私の可愛いが通じない", ONGOING, "○", _, CAT_NORMAL, (M5,)),
    Label(32, "釣って食べたいギャル澤さん", "釣って食べたいギャル澤さん", ONGOING, "○", _, CAT_NORMAL),
    Label(33, "山田くんとLv999の恋をする", "山田くんとLv999の恋をする", ONGOING, "○", _, CAT_NORMAL),
    Label(34, "ペンの夢に紅をさす", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(35, "じゅーくぼっくす", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(36, "パンチラッシュJKタラちゃん", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(37, "グラぱらっ！", "グラぱらっ!", ONGOING, "○", _, CAT_NORMAL),
    Label(38, "見える子ちゃん", "見える子ちゃん", ONGOING, "○", _, CAT_NORMAL, (M6,)),
    Label(39, "俺の女優が一番淫ら", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(40, "パラレルパラダイス", "パラレルパラダイス", ONGOING, "○", _, CAT_NORMAL),
    Label(41, "不徳のギルド", "不徳のギルド", ONGOING, "○", _, CAT_NORMAL),
    Label(42, "魁の花巫女", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(43, "僕のカノジョ先生", "僕のカノジョ先生", ONGOING, "△", MERGED_NOVEL, CAT_NORMAL, (M1, M1A)),
    Label(44, "アダマスの魔女たち", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(45, "トニカクカワイイ", "トニカクカワイイ", ONGOING, "○", _, CAT_NORMAL),
    Label(46, "高嶺の華は乱れ咲き", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(47, "お隣の天使様にいつの間にか駄目人間にされていた件",
          "お隣の天使様にいつの間にか駄目人間にされていた件", ONGOING, "△", MERGED_NOVEL, CAT_NORMAL, (M1,)),
    Label(48, "愛の流星カウーパ", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(49, "ドリーム☆ジャンボ☆ガール", "ドリーム☆ジャンボ☆ガール", ONGOING, "○", _, CAT_NORMAL),
    Label(50, "夫婦以上、恋人未満。(特装版がない場合通常版）", "夫婦以上、恋人未満。", ONGOING, "○", _, CAT_NORMAL, (M7,)),
    Label(51, "サタノファニ", "サタノファニ", ONGOING, "○", _, CAT_NORMAL, (M4, M5, TRANSFER)),
    Label(52, "月曜日のたわわ　青版", "月曜日のたわわ", ONGOING, "△", MERGED_ILLUSTRATION, CAT_NORMAL, (M2, M2A)),
    Label(53, "天晴納涼！！ふんどし刑事", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(54, "それでも明日も彼氏がいい", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(55, "お隣の天使様にいつの間にか駄目人間にされていた件　after the rain", _, NOT_FOUND, "×", _, CAT_PARENT, (M3,)),
    Label(56, "ゾンビ世界でハーレムをつくろう！", _, NOT_FOUND, "×", _, CAT_ABSENT),
    # [57] は当初 `判定不能` とラベルしていたが、測定後に `連載中` へ訂正した（Issue #47）。
    # 訂正の理由は2点。
    #  (1) 地の文が `判定不能` のときインフォボックスの終了系フィールドが空欄なら `連載中` と
    #      読む、というまったく同一の機構で、[13][19][28][52][72] の5行が正答している。
    #      [57] だけ別基準を当てるのは測定として一貫しない。
    #  (2) ラベル付け（ラウンド6）でこの行を提示した際、`終了号 =（空欄）/ 終了日 =（空欄）`
    #      しか示さず、**`巻数 = 既刊8巻（2026年1月現在）` を材料に含めていなかった**。
    #      「既刊」は空欄の消極的解釈ではなく継続中であることの積極的な記録であり、
    #      当初のラベルはこの決定的な材料を欠いた状態での判断だった。
    #      記事の実データも確認済み: 採用された本編ブロックは『リコリス・リコイル』の漫画版
    #      そのもの（コミックフラッパー連載）で、スピンオフ『リコレクト』（終了日あり）とは
    #      正しく区別されている。
    # なお「空欄 ⇒ 連載中 にゲートが無い」という構造上の論点は本行固有ではなく上記6行すべてに
    # 関わるため、ラベルではなく別課題として残す（docs/known_limitations.md 参照）。
    Label(57, "リコリス・リコイル", "リコリス・リコイル", ONGOING, "△", MERGED_ANIME, CAT_NORMAL, (M8,)),
    Label(58, "履いてください、鷹峰さん", "履いてください、鷹峰さん", ONGOING, "○", _, CAT_NORMAL),
    Label(59, "ガイシューイッショク！", "ガイシューイッショク!", ONGOING, "○", _, CAT_NORMAL),
    Label(60, "カレシがいるのに", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(61, "うれしょん", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(62, "せいぶつ部の田辺くん", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(63, "ギルティサークル", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(64, "ゴブリンにエロいことされちゃう　アンソロジー", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(65, "僕の心のヤバイやつ （特装版ない場合通常版）", "僕の心のヤバイやつ", ONGOING, "○", _, CAT_NORMAL, (TRANSFER,)),
    Label(66, "恋愛志向生徒会", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(67, "時々ボソッとロシア語でデレる隣のアーリャさん",
          "時々ボソッとロシア語でデレる隣のアーリャさん", ONGOING, "△", MERGED_NOVEL, CAT_NORMAL, (M1,)),
    Label(68, "普通の本はありません！", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(69, "朝まで恋愛chu！ ～幼なじみはトキめかない？", _, NOT_FOUND, "×", _, CAT_ABSENT, (M9,)),
    Label(70, "経験済みなキミと、経験ゼロなオレが、お付き合いする話。",
          "経験済みなキミと、経験ゼロなオレが、お付き合いする話。", ONGOING, "△", MERGED_NOVEL, CAT_NORMAL, (M1, M1A)),
    Label(71, "触手魔術師の成り上がり（電子版のみ【最終巻】5巻が発売済）", _, NOT_FOUND, "×", _, CAT_ABSENT),
    Label(72, "魔都精兵のスレイブ", "魔都精兵のスレイブ", ONGOING, "○", _, CAT_NORMAL, (M2,)),
)

# 偽陰性率の分母＝期待ステータスが `連載中` または `完結` の行。
# `判定不能` と `記事なし` は #35 §8-2 の定義により分母に入らない。
DENOMINATOR = tuple(label for label in LABELS if label.expected in (ONGOING, COMPLETED))


def _self_check():
    """ラベル定義の整合性を検算する。数値は Issue #47 に記載したものと一致すること。"""
    from collections import Counter

    assert len(LABELS) == 72, len(LABELS)
    assert [label.no for label in LABELS] == list(range(1, 73)), "番号は1〜72で連続すること"
    assert len({label.title for label in LABELS}) == 72, "入力タイトルは重複しないこと"

    for label in LABELS:
        # 期待記事名の有無と期待ステータス・記事実在は連動する
        if label.expected == NOT_FOUND:
            assert label.expected_page is None and label.exists == "×", label.no
        else:
            assert label.expected_page is not None and label.exists in ("○", "△"), label.no
        # merged_into は △ のときだけ持つ
        assert (label.merged_into is not None) == (label.exists == "△"), label.no
        # M-1a は M-1 の下位形、M-2a は M-2 の下位形
        if M1A in label.marks:
            assert M1 in label.marks, label.no
        if M2A in label.marks:
            assert M2 in label.marks, label.no

    status = Counter(label.expected for label in LABELS)
    exists = Counter(label.exists for label in LABELS)
    category = Counter(label.category for label in LABELS)
    marks = Counter(m for label in LABELS for m in label.marks)
    merged = Counter(label.merged_into for label in LABELS if label.merged_into)

    # [57] を `判定不能` → `連載中` に訂正したため、分母は 38 → 39 に増えた（Issue #47）。
    assert status == {ONGOING: 39, NOT_FOUND: 32, UNKNOWN: 1}, status
    assert exists == {"×": 32, "○": 31, "△": 9}, exists
    assert category == {CAT_NORMAL: 40, CAT_ABSENT: 29, CAT_PARENT: 2, CAT_AUTHOR: 1}, category
    assert len(DENOMINATOR) == 39, len(DENOMINATOR)
    # M-2 と M-8 の和集合＝インフォボックス経路で決着した6行、という対応を固定する。
    infobox_marked = {label.no for label in LABELS if M2 in label.marks or M8 in label.marks}
    assert infobox_marked == set(INFOBOX_DECIDED), infobox_marked
    assert marks == {M1: 6, M1A: 2, M2: 5, M2A: 1, M3: 2, M4: 2, M5: 2,
                     M6: 1, M7: 1, M8: 1, M9: 1, TRANSFER: 2}, marks
    assert merged == {MERGED_NOVEL: 7, MERGED_ILLUSTRATION: 1, MERGED_ANIME: 1}, merged

    covered = sum(1 for label in LABELS if label.expected_page is not None)
    assert covered == 40, covered
    return status, exists, category, marks, merged, covered


def main():
    from collections import Counter

    status, exists, category, marks, merged, covered = _self_check()
    print(f"件数: {len(LABELS)}  番号: 1〜{LABELS[-1].no}")
    print(f"\n期待ステータス別: {dict(status)}")
    print(f"  偽陰性率の分母（連載中/完結）: {len(DENOMINATOR)}")
    print(f"\n記事実在別: {dict(exists)}")
    print(f"  △ の統合先種別: {dict(merged)}")
    print(f"  △ の比率: {exists['△']}/72 = {exists['△'] / 72 * 100:.1f}%")
    print(f"\nカテゴリ別: {dict(category)}")
    print(f"\nマーク別:")
    for m in sorted(marks, key=lambda x: (not x.startswith("M-"), x)):
        rows = [label.no for label in LABELS if m in label.marks]
        print(f"  {m:6s} {marks[m]:2d} 件  行: {rows}")
    print(f"  マークなし {sum(1 for label in LABELS if not label.marks):2d} 件")
    print(f"\nWikipedia 記事被覆率: {covered}/72 = {covered / 72 * 100:.1f}%")
    print(f"記事なし率          : {status[NOT_FOUND]}/72 = {status[NOT_FOUND] / 72 * 100:.1f}%")
    print(f"分母 {len(DENOMINATOR)} での1件あたりの変動幅: {100 / len(DENOMINATOR):.2f} ポイント")
    print("\n検算: すべて一致（_self_check の assert が通過）")


if __name__ == "__main__":
    main()
