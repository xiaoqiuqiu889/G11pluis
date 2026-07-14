# V4 美术方向与镜头清单

> 历史美术记录：本文保留既有镜头生成依据；现行叙事契约、交互规则与 canonical 毕业照连续性要求以 [`V5-DESIGN-CONTRACT.md`](./V5-DESIGN-CONTRACT.md) 为准。

## 交付结论

- 生成方式：OpenAI 内置 `image_gen`，每个资产独立生成。
- 新增目录：`public/art-v4/`
- 新增数量：14 张；旧资源 14 张；当前总量 28 张。
- 统一尺寸：1672 × 941，横屏比例约 1.777。
- 接入原则：每张新图都进入主线或记忆剪辑室，不保留未使用的库存图。
- 剧情原则：画面只呈现既定历史与选择前的中性动作，不替玩家预选结果。

## 统一美术圣经

### 画面语言

克制的电影感手绘叙事插画；精细石墨与墨线轮廓；透明水彩和水粉洗色；低饱和炭灰、橄榄绿、褐色与烟熏琥珀；纸张纹理与 35mm 胶片颗粒；自然人体比例；现实主义伊朗与伊朗裔美国生活细节；16:9 单幅连续画面。

禁止：字幕、标题、边框、漫画分格、水印、清晰的虚构波斯文、现代设备穿帮、夸张动漫表情、奖赏式高亮、戏剧化拥抱或替玩家决定选择结果。

### 角色锚点

- 年轻莱拉（21–22）：椭圆脸、深色杏仁眼、浅灰头巾边缘露出松散卷黑发、深橄榄外套、小棕色斜挎包。
- 中年莱拉（约34）：保持相同脸型与眼睛，灰米色头巾、深橄榄外套，鬓边卷发与轻微年龄痕迹。
- 年轻阿拉什（22–23）：瘦高、卷黑发、轻胡茬、深海军蓝夹克。
- 中年阿拉什（约35）：同样的卷发与瘦削轮廓，鬓角灰白、轻胡茬、炭灰长外套。
- 卡姆兰：短卷黑发、矩形眼镜、深色衬衫或连帽衫；疲惫但有独立的黑白摄影兴趣。
- 玛丽亚姆：深蓝头巾、棕色长外套；数学教师，会记录流星，具有独立行动与兴趣。

## 14 张新增镜头及接入位置

| 文件 | 叙事内容 | 主线 / 重访接入 |
|---|---|---|
| `university-gate-autumn.png` | 2008 秋，莱拉第一次站在德黑兰大学门前 | 标题、第一章转场 |
| `underground-projector-close.png` | 停电后两人检修 16mm 放映机 | 第一次主选择、剪辑室第一段 |
| `graduation-photo-day.png` | 两人站在毕业合影两端互望 | “毕业照那天”、第一段未来回声 |
| `student-publication-room.png` | 莱拉、玛兹雅与同学排版刊物 | 第二章转场、刊物场景 |
| `dorm-search-night.png` | 名单、未点燃火柴与逼近的搜查 | 第二次主选择、剪辑室第二段 |
| `university-gate-expulsion.png` | 莱拉在校门外、阿拉什在门内 | 处分后、第二段未来回声 |
| `video-call-kamran.png` | 德黑兰与圣何塞之间的现实视频通话 | 卡姆兰出现与手续推进 |
| `final-rooftop-night.png` | 最后一夜，信封、公交票和两人间的距离 | 第三次主选择、剪辑室第三段 |
| `airport-clock-goodbye.png` | 德黑兰国际出发大厅、安检口与时钟 | 近期回声、第三段未来回声 |
| `localization-office.png` | 莱拉在普通外包公司做波斯语本地化 | “两个城市”蒙太奇镜头 1 |
| `maryam-telescope-rooftop.png` | 玛丽亚姆记录流星，阿拉什安静陪伴 | “两个城市”蒙太奇镜头 2 |
| `email-delete-night.png` | 莱拉删除邮件，卡姆兰冲洗黑白照片 | 邮件共鸣动作及删除后 |
| `istanbul-cafe-arrival.png` | 阿拉什推门，十三年后的第一次对视 | 重逢视线共鸣动作 |
| `poetry-book-photo-close.png` | 同一咖啡馆、同一诗集与其中一张照片 | 诗集与照片连续性场景 |

## 最终提示词集合

所有镜头共同使用：

```text
Use case: stylized-concept
Asset type: 16:9 cinematic game narrative illustration for an interactive film
Style/medium: restrained cinematic hand-drawn narrative illustration; fine graphite and ink contours layered with translucent watercolor and gouache washes; realistic anatomy and urban detail; subtle paper grain and 35mm film grain.
Color palette: low-saturation charcoal gray, olive green, brown, smoky amber, with restrained cool blue-gray where appropriate.
Constraints: one continuous full-bleed frame; preserve the character anchors; natural hands and faces; no readable text; no subtitles, title, border, panel, logo, trademark, or watermark.
Avoid: comic-strip layout, glossy anime rendering, oversaturation, melodrama, malformed anatomy, modern anachronisms, or imagery that predetermines a player choice.
```

逐镜头主请求：

1. `university-gate-autumn.png`：2008 秋日德黑兰大学正门，年轻莱拉抱书停在人流边缘，远处厄尔布尔士山，宽幅建立镜头。
2. `underground-projector-close.png`：革命街旧书店地下室停电，阿拉什用螺丝刀修 16mm 放映机，莱拉举手电照亮齿轮，两人靠近但未接吻。
3. `graduation-photo-day.png`：约十五名学生准备毕业合影，莱拉与阿拉什站在人群两端望向彼此，摄影师背影在前景。
4. `student-publication-room.png`：2009 宿舍小房间，莱拉、玛兹雅和两名学生用打字机、剪贴纸页与胶水排版地下刊物。
5. `dorm-search-night.png`：同一宿舍深夜，莱拉握名单，阿拉什拿未点燃的火柴，门外手电与人影逼近，玛兹雅不在场。
6. `university-gate-expulsion.png`：紧闭校门外莱拉手持处分文件，门内远处阿拉什挂实验室门卡，栅栏压缩两人的世界。
7. `video-call-kamran.png`：德黑兰出租屋，莱拉与圣何塞普通公寓里的卡姆兰视频通话，桌边有移民表格，屏幕无可读文字。
8. `final-rooftop-night.png`：离开前最后一夜，两人在德黑兰屋顶相隔一小段距离，脚边有文件信封，手中有旧公交票，保持选择中性。
9. `airport-clock-goodbye.png`：德黑兰国际机场出发大厅，明确呈现值机柜台、安检入口、抽象航班板与大时钟；莱拉走向安检，阿拉什停在时钟下；绝无铁路元素。
10. `localization-office.png`：圣何塞普通外包公司，成年莱拉戴耳机检查波斯语界面，窗外是停车场和低矮高速公路，不浪漫化硅谷。
11. `maryam-telescope-rooftop.png`：德黑兰屋顶，玛丽亚姆使用旧望远镜记录流星并摊开数学作业本，阿拉什在水箱边喝茶，尊重她的专注。
12. `email-delete-night.png`：圣何塞公寓凌晨，中年莱拉的手停在删除键，背景中卡姆兰在厨房暗房晾挂黑白停车场照片。
13. `istanbul-cafe-arrival.png`：雨后卡拉柯伊老咖啡馆，中年莱拉坐在窗边，桌上糖罐与一张毕业照；中年阿拉什刚推门，两人保持距离。
14. `poetry-book-photo-close.png`：延续同一咖啡馆桌面与雨光，阿拉什打开发黄开裂的诗集，唯一一张毕业照位于书页之间，莱拉的手停在桌沿。

## 连续性约束

- 照片共两张同版冲洗件：序章莱拉携带一张；诗集里是阿拉什保存的另一张。近景镜头只展示诗集中的一张，不在同一画面复制。
- 第三章离开使用德黑兰国际机场；美国抵达使用 SFO；任何机场镜头都禁止铁路、站台、列车或火车站构图。
- 最后一夜画面不表现“坦白 / 请求同行 / 隐瞒”中的任何一个结果，只摆放三条路线都成立的信封与旧公交票。
- 选择二画面中的火柴未点燃，确保三个名单选择都仍然可能。
- 玛丽亚姆和卡姆兰均通过个人兴趣建立主体性，避免把现任伴侣仅表现为照料义务。

## 技术接入

- `Scene` 增加可选 `arts` 数组。
- 蒙太奇依据当前段落索引切换对应镜头，并使用短淡入，不增加操作次数。
- 当前幕和后两幕美术会预加载，降低高分辨率切图产生黑帧的概率。
- 所有图片继续经过统一的饱和度、对比度、亮度、暗角和胶片颗粒层，统一不同批次生成的视觉观感。
