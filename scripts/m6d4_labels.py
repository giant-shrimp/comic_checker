"""M6-D-4（Issue #53）の人手ラベル。**このファイルがラベルの正である。**

Issue #53 のコメントに載せた表は測定時点のスナップショットにすぎない（Issue はコードと
一緒に diff できないため）。ラベルを修正した場合、その diff がレビュー対象になる。

## なぜコードとして持つのか

当初はラベルを、調査スクリプトの出力 JSON（`.m6d4_result.json`）の並び順に対する添字として
扱っていた。**Issue #56 の実装後に調査スクリプトを再実行したところ、その JSON が上書きされ、
96行のラベルを失いかけた**（scratchpad の控えから復元できたが、記録としては危うい）。
#51 の `scripts/m6d3_labels.py` と同じく、ラベルは追跡ファイルとして持つ。

**調査の出力（`.m6d4_*.json`、gitignore 済み）とラベル（このファイル）は別物である。**
調査を何度再実行してもラベルは動かない。

## 母集団と観測日

- **観測日 2026-07-29。** `巻数` フィールドの実値はこの日に取得したもの。記事は編集される
  ので、再測定するときは取り直すこと。
- **本調査 75行**: `hastemplate:"Infobox animanga/Manga"` の `sroffset` 0〜1750 から
  1,800記事を取り、「地の文が `判定不能` かつインフォボックスが `連載中`」だった行の全数。
- **ホールドアウト 21行**: 同じクエリの `sroffset` 1800〜2250 から500記事。**閾値を選んだ
  標本と評価する標本を分けるため**に別に取った（`ERRORS.md` の該当項を参照）。

## ラベルの意味

`label` は**実際に完結しているか**の人手判定である。この96行はいずれも「実装が `連載中` と
答えた行」なので、`完結` はそのまま**誤答**を意味する。

| 群 | 完結（＝誤答） | 連載中（＝正答） | 失敗率 |
|---|---|---|---|
| 本調査 75行 | 46 | 29 | **61.3%** |
| ホールドアウト 21行 | 13 | 8 | **61.9%** |

2つの独立した標本で率がほぼ一致した。

## 列の意味

- `group`   : `本調査` / `ホールドアウト`
- `no`      : 群ごとの通し番号。**振り直さないこと**（Issue #53 のコメントの表と対応する）
- `title`   : 記事名
- `volumes` : `巻数` フィールドの**生値**。`<br>` や `<ref>` 等のタグを除去していない。
              Issue #56 の判定は除去せずに走査するので、加工するとテストの土俵がずれる。
              `None` はフィールド自体が存在しないことを意味する
- `label`   : `完結` / `連載中`
"""

COMPLETED = "完結"
ONGOING = "連載中"

MAIN = "本調査"
HOLDOUT = "ホールドアウト"


class Label:
    __slots__ = ("group", "no", "title", "volumes", "label")

    def __init__(self, group, no, title, volumes, label):
        self.group = group
        self.no = no
        self.title = title
        self.volumes = volumes
        self.label = label


_ = None  # volumes の「フィールドなし」を短く書くための別名

LABELS = (

    # --- 本調査 ---
    Label(MAIN, 1, 'ゴルゴ13', '既刊221巻<br>（SPコミックス版、2026年7月現在）', ONGOING),
    Label(MAIN, 2, 'ドラゴンボール超', '既刊24巻（2025年4月現在）', ONGOING),
    Label(MAIN, 3, '笑ゥせぇるすまん', '全5巻（[[中公文庫]]）', COMPLETED),
    Label(MAIN, 4, 'もし高校野球の女子マネージャーがドラッカーの『マネジメント』を読んだら', '既刊3巻', COMPLETED),
    Label(MAIN, 5, 'ガンダム Gのレコンギスタ', '既刊5巻（2017年5月現在）', COMPLETED),
    Label(MAIN, 6, 'ギャートルズ', _, COMPLETED),
    Label(MAIN, 7, '21エモン', '4巻（てんとう虫コミックス）他', COMPLETED),
    Label(MAIN, 8, 'かりあげクン', '既刊69巻（2026年1月15日現在）', ONGOING),
    Label(MAIN, 9, '機動戦士ガンダム外伝 宇宙、閃光の果てに…', '全3巻', COMPLETED),
    Label(MAIN, 10, '遠い海から来たCOO', '全2巻 p168+p184', COMPLETED),
    Label(MAIN, 11, '機動戦士ガンダム外伝 THE BLUE DESTINY', '全1巻', COMPLETED),
    Label(MAIN, 12, '機動戦士ガンダム戦記 Lost War Chronicles', 'いずれも全2巻', COMPLETED),
    Label(MAIN, 13, 'BLACK LAGOON', '既刊13巻（2023年12月現在）', ONGOING),
    Label(MAIN, 14, '働きマン', '既刊5巻（2024年6月現在）', ONGOING),
    Label(MAIN, 15, '機動戦士ガンダム ピューリッツァー -アムロ・レイは極光の彼方へ-', '既刊5巻（2026年3月26日現在）', ONGOING),
    Label(MAIN, 16, 'マギアレコード 魔法少女まどか☆マギカ外伝', '既刊12巻（2025年12月現在）', ONGOING),
    Label(MAIN, 17, 'ガンダムパイロット列伝 蒼穹の勇者達', _, COMPLETED),
    Label(MAIN, 18, '電脳コイル', '全1巻', COMPLETED),
    Label(MAIN, 19, '深夜食堂', '既刊30巻（2025年9月30日現在）', ONGOING),
    Label(MAIN, 20, '科学漫画サバイバルシリーズ', _, COMPLETED),
    Label(MAIN, 21, 'すべてがFになる', '全1巻', COMPLETED),
    Label(MAIN, 22, 'OVERMANキングゲイナー', _, COMPLETED),
    Label(MAIN, 23, 'BASTARD!! -暗黒の破壊神-', '既刊27巻（2012年3月現在）', COMPLETED),
    Label(MAIN, 24, 'HUNTER×HUNTER', '既刊39巻（2026年7月現在）', ONGOING),
    Label(MAIN, 25, 'とある魔術の禁書目録', '既刊33巻（2026年2月現在）', ONGOING),
    Label(MAIN, 26, 'まちカドまぞく', '既刊6巻（2021年2月現在）', COMPLETED),
    Label(MAIN, 27, '土竜の唄', '既刊95巻（2026年5月29日現在）', ONGOING),
    Label(MAIN, 28, '魔動王グランゾート', _, COMPLETED),
    Label(MAIN, 29, '高橋留美子劇場', '既刊6巻（2024年3月29日現在）', ONGOING),
    Label(MAIN, 30, '鬼平犯科帳', '単行本：既刊127巻（2026年4月現在）<br />ワイド版：既刊65巻（2026年4月現在）<br />文庫版：既刊77巻（2025年4月現在）', ONGOING),
    Label(MAIN, 31, 'アルドノア・ゼロ', '全4巻<br />全5巻（2nd Season）', COMPLETED),
    Label(MAIN, 32, '太極千字文', '全25巻', COMPLETED),
    Label(MAIN, 33, 'ログ・ホライズン', '既刊1巻（2013年2月現在）', COMPLETED),
    Label(MAIN, 34, '春庭家の3人目', '全2巻', COMPLETED),
    Label(MAIN, 35, '死神くん', '全13巻', COMPLETED),
    Label(MAIN, 36, 'ちっちゃな雪使いシュガー', '全3巻', COMPLETED),
    Label(MAIN, 37, 'フューチャーカード 神バディファイト', '全4巻', COMPLETED),
    Label(MAIN, 38, '超時空要塞マクロスII -LOVERS AGAIN-', '全1巻', COMPLETED),
    Label(MAIN, 39, 'コボちゃん', '既刊120巻（蒼鷹社版全60巻+芳文社版既刊61巻）<br />（2026年7月現在）', ONGOING),
    Label(MAIN, 40, 'フリクリ', '全2巻', COMPLETED),
    Label(MAIN, 41, '空の境界', '既刊12巻（2023年12月現在）', COMPLETED),
    Label(MAIN, 42, 'ドラゴンクライシス!', '全1巻', COMPLETED),
    Label(MAIN, 43, '銀河鉄道物語', _, COMPLETED),
    Label(MAIN, 44, '桃華月憚', '全2巻', COMPLETED),
    Label(MAIN, 45, '青山剛昌短編集', '全1巻', COMPLETED),
    Label(MAIN, 46, '失格紋の最強賢者', '既刊35巻（2026年6月現在）', ONGOING),
    Label(MAIN, 47, 'あっちこっち', '既刊10巻（2025年3月現在）', ONGOING),
    Label(MAIN, 48, 'あひるの空', '全50巻<br>（あひるの空）<br>既刊1巻（2019年6月現在）<br>（あひるの空 THE DAY）', COMPLETED),
    Label(MAIN, 49, 'カッコウの許嫁', '既刊33巻（2026年6月現在）', ONGOING),
    Label(MAIN, 50, '現実主義勇者の王国再建記', '既刊15巻（2026年6月現在）', ONGOING),
    Label(MAIN, 51, 'ぐらんぶる', '既刊26巻（2026年4月7日現在）', ONGOING),
    Label(MAIN, 52, 'OZ (樹なつみの漫画)', _, COMPLETED),
    Label(MAIN, 53, 'おとめ妖怪 ざくろ', '既刊10巻（2015年4月時点）', COMPLETED),
    Label(MAIN, 54, '乱歩奇譚 Game of Laplace', '全2巻', COMPLETED),
    Label(MAIN, 55, '支配者の黄昏', '全1巻', COMPLETED),
    Label(MAIN, 56, 'ミラクルジャイアンツ童夢くん', _, COMPLETED),
    Label(MAIN, 57, 'アリスと蔵六', '既刊13巻（2024年12月現在）', ONGOING),
    Label(MAIN, 58, '百鬼夜行抄', '単行本：既刊32巻（2026年4月現在）<br />文庫本：既刊21巻（2025年2月現在）', ONGOING),
    Label(MAIN, 59, '大怪獣バトル ウルトラアドベンチャー', '『無印』全3巻（未完）、新装版全2巻<br />『NEO』未発売', COMPLETED),
    Label(MAIN, 60, 'この素晴らしい世界に祝福を!', '既刊22巻（2026年2月現在）', ONGOING),
    Label(MAIN, 61, 'Fate/hollow ataraxia', '既刊2巻（2016年6月現在）', COMPLETED),
    Label(MAIN, 62, 'ゆめりあ', '全1巻', COMPLETED),
    Label(MAIN, 63, 'リコリス・リコイル', '既刊8巻（2026年1月現在）', ONGOING),
    Label(MAIN, 64, '手塚治虫の旧約聖書物語', '全3巻', COMPLETED),
    Label(MAIN, 65, '青の祓魔師', '既刊34巻（2026年5月現在）', ONGOING),
    Label(MAIN, 66, '賢者の孫', '既刊28巻（2026年2月現在）', ONGOING),
    Label(MAIN, 67, 'スーパーロボット大戦ORIGINAL GENERATION THE ANIMATION', _, COMPLETED),
    Label(MAIN, 68, 'ねこねこ日本史', '既刊17巻（2026年2月5日現在）', ONGOING),
    Label(MAIN, 69, 'Ef - a fairy tale of the two.', '既刊10+1巻', COMPLETED),
    Label(MAIN, 70, 'トリアージX', '既刊31巻（2026年6月現在）', ONGOING),
    Label(MAIN, 71, '全力ウサギ', '全4巻', COMPLETED),
    Label(MAIN, 72, 'Fate/strange Fake', '既刊5巻（2022年2月現在）', ONGOING),
    Label(MAIN, 73, 'ケシカスくん', '既刊22巻+傑作選', ONGOING),
    Label(MAIN, 74, '早子先生、結婚するって本当ですか?', _, COMPLETED),
    Label(MAIN, 75, 'ノブナガ・ザ・フール', '既刊2巻', COMPLETED),
    # --- ホールドアウト ---
    Label(HOLDOUT, 1, 'HAUNTEDじゃんくしょん', '全13巻', COMPLETED),
    Label(HOLDOUT, 2, 'マンガ日本経済入門', _, COMPLETED),
    Label(HOLDOUT, 3, '転生したらスライムだった件', '既刊32巻（2026年6月現在）', ONGOING),
    Label(HOLDOUT, 4, '荒野のコトブキ飛行隊', '全1巻', COMPLETED),
    Label(HOLDOUT, 5, '快傑蒸気探偵団', '全8巻', COMPLETED),
    Label(HOLDOUT, 6, '初めて恋をした日に読む話', '既刊20巻（2026年7月23日現在）<ref name="hajikoi">{{Cite web|和書|url=https://books.shueisha.co.jp/search/search.html?seriesid=35792&order=1 |title=「初めて恋をした日に読む話」コミックス一覧 |accessdate=2026-07-23}}</ref>', ONGOING),
    Label(HOLDOUT, 7, 'HEROMAN', '全5巻', COMPLETED),
    Label(HOLDOUT, 8, 'やくならマグカップも', '既刊46巻', ONGOING),
    Label(HOLDOUT, 9, '薬師寺涼子の怪奇事件簿', _, COMPLETED),
    Label(HOLDOUT, 10, '新白雪姫伝説プリーティア', '全4巻', COMPLETED),
    Label(HOLDOUT, 11, '俺、つしま', '既刊4巻（2024年4月現在）', COMPLETED),
    Label(HOLDOUT, 12, '鋼鉄三国志', _, COMPLETED),
    Label(HOLDOUT, 13, '遙かなる時空の中で3', '「遙かなる時空の中で」11巻に収録<br />書き下ろしおまけ漫画も収録', COMPLETED),
    Label(HOLDOUT, 14, 'ネットゴーストPIPOPA', '全2巻', COMPLETED),
    Label(HOLDOUT, 15, '佐々木と宮野', '既刊11巻（2026年2月現在）', ONGOING),
    Label(HOLDOUT, 16, 'ジャヒー様はくじけない!', '既刊12巻（2025年11月20日現在）', ONGOING),
    Label(HOLDOUT, 17, '一人之下', _, ONGOING),
    Label(HOLDOUT, 18, '白い砂のアクアトープ', '全3巻', COMPLETED),
    Label(HOLDOUT, 19, '裏世界ピクニック', '既刊16巻（2026年5月現在）', ONGOING),
    Label(HOLDOUT, 20, 'レベルE', '全3巻（ジャンプ・コミックス）<br />全2巻（[[集英社文庫|コミック文庫]]・[[集英社ジャンプリミックス|SJR]]）', COMPLETED),
    Label(HOLDOUT, 21, '岸辺露伴は動かない', '既刊3巻（2025年5月現在）', ONGOING),
)
