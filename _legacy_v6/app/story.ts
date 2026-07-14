import type { Axis, EndingKey } from "./game-logic";

export type MainOption = {
  id: string; label: string; detail: string; axis: Axis; motif: string; sound: string;
  /** 当场发生的动作。旧场景副本可能缺省，渲染时可回退到 memory。 */
  action?: string; memory: string; confirmation: string; nearEcho: string; farEcho: string;
  endingFragment: string; revisitEcho: string;
};

export type ResonanceOption = {
  id: string; label: string; detail: string; motif: string; sound: string;
  /** 共鸣动作把操作、感官确认、远期回响与结尾镜头分开保存。 */
  action?: string; confirmation: string; echo: string; farEcho?: string; endingFragment: string;
};

export type ChapterId = "chapter1" | "chapter2" | "chapter3" | "chapter4" | "chapter5";

export type Scene = {
  id: string; kind: "chapter" | "narrative" | "montage" | "choice" | "echo" | "resonance" | "revisitEcho";
  chapter: string; chapterLabel: string; place: string; year?: string; speaker?: string;
  body?: string[]; beats?: string[]; art?: string; arts?: string[]; artFocus?: string; object?: string; canonicalPhoto?: string;
  progressive?: boolean; choiceId?: string; resonanceId?: string;
  choices?: MainOption[]; resonances?: ResonanceOption[];
  /** 可在场景中完成的探索、操作或抉择；ID 与 progression catalog 保持一致。 */
  interactionIds?: string[];
  /** 本场景可选的本地模拟付费对话。 */
  paidDialogueId?: string;
  /** 章节结算与故事内奖励均挂在章节最后一个可玩场景。 */
  chapterEnd?: ChapterId;
  rewardId?: ChapterId;
  /** 记忆剪辑室重访本幕时使用的短上下文。 */
  revisitBody?: string[];
};

export const axisNames: Record<Axis, string> = {
  "speak": "说出",
  "keep": "留住",
  "survive": "活下去"
};
export const axisExplanations: Record<Axis, string> = {
  "speak": "把爱、责任和真相说出口——它后来被称作理想。",
  "keep": "让一个吻、一本书和共同未来留在手里——它后来被称作爱情。",
  "survive": "先保护自己，再承担离开后的生活——它后来被称作生存。"
};
export const memoryContracts: Record<string, MainOption[]> = {
  "choice-one": [
    {
      "id": "poem",
      "label": "送他一首诗",
      "detail": "让纸替她说出还不敢承认的话",
      "axis": "speak",
      "motif": "折诗",
      "sound": "paper",
      "action": "她撕下诗页，沿原有的折痕折了四次，放进男生的工具盒。",
      "memory": "她把诗留给他，相信文字能穿过停电后的黑暗。",
      "confirmation": "纸被折了四次，刚好能藏进他的工具盒。",
      "nearEcho": "男生后来每次修放映机，都先把那张折诗从工具盒里取出来，放到不会沾上机油的地方。",
      "farEcho": "十三年后，他没有背诵诗句，只说自己一直记得纸被折过的方向。",
      "endingFragment": "你让那首没有署名的诗留下。它没有替他们找到出口，却让一句未说完的话抵达了另一个人。",
      "revisitEcho": "旧工具盒里，多了一张沿折痕发白的诗页。"
    },
    {
      "id": "kiss",
      "label": "主动吻他",
      "detail": "在电影重新亮起前先靠近一步",
      "axis": "keep",
      "motif": "照片",
      "sound": "photo",
      "action": "放映机停下以后，她先向前一步，吻了男生。",
      "memory": "停电的夜里，她先吻了他。",
      "confirmation": "电影还没有恢复，他们已经有了一段只属于黑暗的画面。",
      "nearEcho": "此后每次停电，男生都会下意识伸手找她；女生总比他早半步碰到那只手。",
      "farEcho": "咖啡馆的灯闪了一下，他们都抬起头，却没有再靠近。",
      "endingFragment": "你留住了停电时的那个吻。它没有要求后来的人生作证，只证明他们曾经毫不犹豫地靠近。",
      "revisitEcho": "黑暗里，两只手再次先于语言找到彼此。"
    },
    {
      "id": "leave",
      "label": "先行离开",
      "detail": "把心动收好，给自己一个夜晚",
      "axis": "survive",
      "motif": "电影票",
      "sound": "ticket",
      "action": "她把电影票收进口袋，先沿楼梯走回街上。",
      "memory": "她先走下楼梯，脚步很稳，心跳不是。",
      "confirmation": "第二天，她仍比约定早到了十分钟。",
      "nearEcho": "那以后女生总会提前确认出口，也总会在确认安全后第一个回来。",
      "farEcho": "重逢时，她先看见咖啡馆的后门；确认出口以后，才允许自己认真看他。",
      "endingFragment": "你保留了她先离开的能力。那不是拒绝，而是她很早就学会的事：勇气有时需要一条看得见的退路。",
      "revisitEcho": "她记住了出口，也记住了自己第二天仍然回来。"
    }
  ],
  "choice-two": [
    {
      "id": "reporter",
      "label": "只承认自己",
      "detail": "承认自己参与刊物，但不提供任何同伴姓名",
      "axis": "speak",
      "motif": "供词",
      "sound": "paper",
      "action": "她承认自己参与编辑，把责任只写在自己名下。",
      "memory": "她只说自己的事，不替任何人作证。",
      "confirmation": "记录员追问三次，她三次重复同一句。",
      "nearEcho": "纪律委员会拿着已有材料追问同伴，女生只承认自己的文章。处分照样落下。",
      "farEcho": "男生翻到夹着处分通知的书页，仍记得她当年把每一句供词的主语都写成“我”。",
      "endingFragment": "你让她只承认自己的部分。她没有替同伴作证，也没有因此逃过处分。",
      "revisitEcho": "调查者换了三种问法，她只用“我”回答。"
    },
    {
      "id": "book",
      "label": "拒绝告发",
      "detail": "一个名字也不说，让沉默保护同伴",
      "axis": "keep",
      "motif": "诗集",
      "sound": "paper",
      "action": "她合上问话记录，一个同伴的名字也没有说。",
      "memory": "她拒绝指认任何同伴，把沉默留在记录里。",
      "confirmation": "房间里只剩钟表声。",
      "nearEcho": "问话记录写着“拒绝回答”。学校把沉默也算成了证据。",
      "farEcho": "十三年后，诗集里仍夹着那张处分通知；“拒绝回答”四个字已经发黄。",
      "endingFragment": "你让她拒绝告发。沉默没有撤销处分，却把同伴的名字留在她自己的记忆里。",
      "revisitEcho": "记录停在空白处，处分通知后来被夹进诗集。"
    },
    {
      "id": "burn",
      "label": "说出名字",
      "detail": "提供调查者追问的姓名，换取减轻处理",
      "axis": "survive",
      "motif": "笔迹",
      "sound": "ash",
      "action": "她说出三个名字；调查者早已在材料上把他们圈了出来。",
      "memory": "她说出了三个名字，希望学校减轻处理。",
      "confirmation": "笔尖停下时，她没有抬头。",
      "nearEcho": "处理没有真正减轻。她第一次知道，妥协也可能什么都换不来。",
      "farEcho": "诗集里夹着处分通知，供词栏有三个被划过的名字。男生没有替她解释。",
      "endingFragment": "你让她说出三个调查者早已圈出的名字。处理没有减轻，这个动作也没有被结局原谅或定罪。",
      "revisitEcho": "三个名字落在纸上，处理决定仍然没有变。"
    }
  ],
  "choice-three": [
    {
      "id": "truth",
      "label": "把一切一次说完",
      "detail": "把卡姆兰、婚姻、机票、害怕和仍然爱他一次说完",
      "axis": "speak",
      "motif": "未寄出的信",
      "sound": "paper",
      "action": "她说出卡姆兰的名字，也说出婚姻、机票、害怕和仍然爱他。",
      "memory": "她把最难听的真话留给了最爱的人。",
      "confirmation": "真话没有使夜晚更轻，但没有留下猜测。",
      "nearEcho": "国际出发大厅里，男生没有追问卡姆兰。他只是把她行李箱松开的搭扣重新扣好，然后退回大厅时钟下面。",
      "farEcho": "绿灯前，男生没有再问卡姆兰是谁；那个名字早已在最后一夜说完。",
      "endingFragment": "你让婚姻、恐惧和爱情同时被说出。真相没有挽留任何人，却使他们不必用余生猜测那场离开的名字。",
      "revisitEcho": "出发大厅的沉默里，不再藏着一个未被说出的名字。"
    },
    {
      "id": "escape",
      "label": "再问一条共同的路",
      "detail": "先说清卡姆兰，再问男生是否愿意一起寻找另一条路",
      "axis": "keep",
      "motif": "两张车票",
      "sound": "ticket",
      "action": "她先说清卡姆兰，再问男生愿不愿意和她寻找另一条离开的路。",
      "memory": "她最后问了一次，而他的沉默就是回答。",
      "confirmation": "城市很大，却没有一条他们共同的出口。",
      "nearEcho": "男生赶到机场时仍带着两张旧公交票，像是误拿了某个本来可以成真的未来。",
      "farEcho": "绿灯前，男生把手从外套口袋里抽出来；那两张旧公交票仍夹在诗集末页。",
      "endingFragment": "你让她最后一次伸手要一个共同未来。男生没有接住，但那次请求使他们都无法把分离伪装成误会。",
      "revisitEcho": "诗集末页，多了两张没能把他们带到同一个出口的公交票。"
    },
    {
      "id": "conceal",
      "label": "只说航班已经确定",
      "detail": "只说航班已经确定，把卡姆兰的名字留在信封里",
      "axis": "survive",
      "motif": "行李牌",
      "sound": "ticket",
      "action": "她只说航班已经确定，把写着卡姆兰名字的文件留在信封里。",
      "memory": "她省略了婚姻，把最锋利的部分留给自己。",
      "confirmation": "她先确认了航班和登机口，才允许自己哭。",
      "nearEcho": "安检口前男生问还有没有别的事。女生握紧行李牌，说没有。登机广播仍准时响起。",
      "farEcho": "路口，她先说卡姆兰正在等她；十三年前留在信封里的名字终于抵达街上。",
      "endingFragment": "你让她保留了最后一点能继续行动的体面。隐瞒留下伤口，也让她在那个早晨没有失去离开的力气。",
      "revisitEcho": "行李牌上的目的地清楚，告别里的原因仍然空白。"
    }
  ]
};
export const resonanceContracts: Record<string, ResonanceOption[]> = {
  "photo": [
    {
      "id": "front",
      "label": "正面朝上",
      "detail": "让照片里两个人继续看着彼此",
      "motif": "照片正面",
      "sound": "photo",
      "action": "她把毕业照正面朝上，放进糖罐旁的空位。",
      "echo": "她把自己的那张毕业照正面朝上，压在糖罐旁。",
      "farEcho": "男生翻开诗集时，里面那张同版毕业照也正面朝上；两张照片隔着桌面再次对齐。",
      "endingFragment": "桌上那张照片始终正面朝上；年轻的他们替现在的两个人完成了最后一次对视。",
      "confirmation": "糖罐旁留出一个刚好够照片的位置。"
    },
    {
      "id": "back",
      "label": "反面朝上",
      "detail": "只留下背面的日期和地点",
      "motif": "照片背面",
      "sound": "photo",
      "action": "她把毕业照翻到背面，让日期朝向灯光。",
      "echo": "她把照片翻到背面，只露出毕业日期和一句已经褪色的手写地点。",
      "farEcho": "诗集里的同版毕业照露出正面，桌上那张仍只用背面的日期回答它。",
      "endingFragment": "桌上的照片一直反扣着。结尾没有脸，只有日期证明那一天确实发生过。",
      "confirmation": "纸面擦过桌布，只剩日期朝向灯光。"
    },
    {
      "id": "bag",
      "label": "暂时收回包里",
      "detail": "先不让过去替今天开口",
      "motif": "帆布包",
      "sound": "photo",
      "action": "她把毕业照滑回帆布包，拉上拉链。",
      "echo": "她把照片收回包里，决定先用现在的眼睛见他。",
      "farEcho": "诗集里的同版毕业照被摊开；女生没有从包里取出自己的那张，只隔着帆布摸到硬边。",
      "endingFragment": "直到离开咖啡馆，她才从包里摸到照片的硬边；过去没有被展示，也没有被丢弃。",
      "confirmation": "帆布包的拉链合上，照片留在离她最近的暗处。"
    }
  ],
  "email": [
    {
      "id": "basement",
      "label": "“我记得地下室的味道。”",
      "detail": "写下最具体的那一晚",
      "motif": "删除键",
      "sound": "email",
      "action": "她在邮件里写下地下室的味道，又点下删除，把整句清空。",
      "echo": "光标停在“地下室的味道”后面。她点下删除，输入框重新变空。",
      "farEcho": "门被推开时，雨水和热灯泡的气味一起进来；她先认出那个被删除过的夜晚。",
      "endingFragment": "她曾写下地下室潮湿的纸张和热灯泡气味，后来删掉了；重逢时，那气味仍先于对白回来。",
      "confirmation": "点下删除前，光标又闪了两次。"
    },
    {
      "id": "book",
      "label": "“那本诗集还在吗？”",
      "detail": "问一个她其实害怕知道答案的问题",
      "motif": "邮件草稿",
      "sound": "email",
      "action": "她在邮件里问诗集是否还在，停了一分钟，再点下删除。",
      "echo": "问题写完以后，她没有按发送。她不确定自己想问的是书，还是书里仍被保管的那些人。",
      "farEcho": "男生推门时把旧诗集抱在臂弯里，替一封没有寄出的邮件带来了答案。",
      "endingFragment": "她曾在邮件里问诗集是否还在，又删掉了。十三年后，男生用把书放到桌上的动作回答了她。",
      "confirmation": "她在问号后停了一分钟。"
    },
    {
      "id": "well",
      "label": "“我现在过得很好。”",
      "detail": "写下一句既真实又不完整的话",
      "motif": "未发送",
      "sound": "email",
      "action": "她写下自己过得很好，看完一遍，再点下删除。",
      "echo": "她看着“很好”两个字，承认生活确实已经有了重量，然后删掉整句。",
      "farEcho": "他确实来了，却只站在时钟下面；她没有再用一句“很好”概括十三年。",
      "endingFragment": "她曾想告诉他自己过得很好。那不是炫耀，也不是谎言；只是完整生活无法被压进一封旧情人的邮件。",
      "confirmation": "这句话是真的，只是不完整。"
    }
  ],
  "gaze": [
    {
      "id": "hands",
      "label": "先看他的白发与手",
      "detail": "辨认时间留在一个人身上的地方",
      "motif": "手与白发",
      "sound": "photo",
      "action": "她把焦点移到他端茶的手与鬓角的白发。",
      "echo": "她先认出他端茶时仍会用拇指摩挲杯沿，只是手背多了细纹。",
      "farEcho": "最后的焦点停在他放开茶杯的手上，随后才让人群重新清晰。",
      "endingFragment": "最后的镜头停在他放开茶杯的手上。亲密感没有消失，只是失去了继续使用的权利。",
      "confirmation": "十三年先落在指节和鬓角。"
    },
    {
      "id": "book",
      "label": "先看发黄的诗集",
      "detail": "确认那些被保管的纸页",
      "motif": "发黄书页",
      "sound": "paper",
      "action": "她把焦点移到诗集开裂的书脊与发黄的纸页。",
      "echo": "她先看见诗集书脊上的裂口，才抬头看男生。",
      "farEcho": "最后的焦点越过人群，落在他臂弯里的旧诗集上。",
      "endingFragment": "最后的镜头越过人群，停在他臂弯里的旧诗集上。被保存不等于能回去。",
      "confirmation": "书页的颜色比记忆更诚实。"
    },
    {
      "id": "clock",
      "label": "先看时钟与机场方向",
      "detail": "记住现实仍在等待",
      "motif": "站钟",
      "sound": "ticket",
      "action": "她把焦点移到站钟与指向机场的路牌。",
      "echo": "她先确认去机场还有四十分钟，也看见男生手机上来自家人的未接来电。",
      "farEcho": "最后的焦点停在绿灯和机场方向牌上，现实仍按自己的时刻表向前。",
      "endingFragment": "最后的镜头停在绿灯和机场方向牌上。两个人都已经有人在现实生活里等待。",
      "confirmation": "四十分钟后，机场班车不会等她。"
    }
  ]
};
export const scenes: Scene[] = [
  {
    "id": "photo",
    "kind": "resonance",
    "chapter": "prologue",
    "chapterLabel": "序章 · 一张照片",
    "place": "伊斯坦布尔 · 十三年后",
    "year": "十三年后",
    "art": "/art-v5/istanbul-cafe-photo-close.png",
    "canonicalPhoto": "/art-v5/canonical-graduation-photo.png",
    "artFocus": "table",
    "object": "photo",
    "resonanceId": "photo",
    "interactionIds": ["photo-placement"],
    "revisitBody": [
      "门还没有响。照片仍在她手里；你可以重新决定过去怎样先抵达桌面。"
    ],
    "resonances": [
      {
        "id": "front",
        "label": "正面朝上",
        "detail": "让照片里两个人继续看着彼此",
        "motif": "照片正面",
        "sound": "photo",
        "echo": "她把自己的那张毕业照正面朝上，压在糖罐旁。",
        "endingFragment": "桌上那张照片始终正面朝上；年轻的他们替现在的两个人完成了最后一次对视。",
        "confirmation": "糖罐旁留出一个刚好够照片的位置。"
      },
      {
        "id": "back",
        "label": "反面朝上",
        "detail": "只留下背面的日期和地点",
        "motif": "照片背面",
        "sound": "photo",
        "echo": "她把照片翻到背面，只露出毕业日期和一句已经褪色的手写地点。",
        "endingFragment": "桌上的照片一直反扣着。结尾没有脸，只有日期证明那一天确实发生过。",
        "confirmation": "纸面擦过桌布，只剩日期朝向灯光。"
      },
      {
        "id": "bag",
        "label": "暂时收回包里",
        "detail": "先不让过去替今天开口",
        "motif": "帆布包",
        "sound": "photo",
        "echo": "她把照片收回包里，决定先用现在的眼睛见他。",
        "endingFragment": "直到离开咖啡馆，她才从包里摸到照片的硬边；过去没有被展示，也没有被丢弃。",
        "confirmation": "帆布包的拉链合上，照片留在离她最近的暗处。"
      }
    ],
    "body": [
      "十三年后，女生先到了咖啡馆。桌上是一张她从圣何塞带来的毕业照。门还没有响，她要把照片放在哪里？"
    ]
  },
  {
    "id": "chapter-one",
    "kind": "chapter",
    "chapter": "chapter1",
    "chapterLabel": "第一章",
    "place": "革命街上的恋人",
    "year": "德黑兰 · 2008",
    "art": "/art-v4/university-gate-autumn.png",
    "body": [
      "有些故事开始时，并不知道自己将成为回忆。"
    ]
  },
  {
    "id": "campus",
    "kind": "narrative",
    "chapter": "chapter1",
    "chapterLabel": "第一章 · 革命街上的恋人",
    "place": "德黑兰大学 / 革命街",
    "art": "/art-v3/tehran-literature-class.png",
    "object": "ticket",
    "interactionIds": ["projector-repair"],
    "body": [
      "女生在文学课上追问诗里的那把钥匙，最后一排的男生低头笑了一下。下课后，他把一张地下电影票夹进她的书里。晚上八点，她在旧书店地下室看见他拆开一台比他们年纪更大的放映机。",
      "停电时，电影只剩声音。男生把胶片头递给她：“别松手。”他举着螺丝刀靠近，女生看不见画面，只听得见两个人的呼吸。"
    ]
  },
  {
    "id": "choice-one",
    "kind": "choice",
    "chapter": "chapter1",
    "chapterLabel": "第一次保存",
    "place": "停电后的地下室",
    "art": "/art-v4/underground-projector-close.png",
    "body": [
      "灯泡重新亮起，字幕条却上下颠倒。女生踩上木椅念反字，男生扶住椅背。她把“我们迟到了”译成“你迟到了”；他看了一眼手表：“八点零三分，我已经在这儿。”",
      "男生在电影票背面写下“20:03”，用沾机油的拇指按在旁边。女生把半颗石榴放进空片盒，叫它维修费。片盒合上时，灯泡又闪了一下，地下室重新暗下来。",
      "“看不见画面，故事也不会消失。”停电还没结束。女生先做了什么？"
    ],
    "choiceId": "choice-one",
    "interactionIds": ["first-memory-action"],
    "revisitBody": [
      "旧胶片停在这一格。沿用旧动作，或重新决定她在黑暗里先做什么。"
    ],
    "choices": [
      {
        "id": "poem",
        "label": "送他一首诗",
        "detail": "让纸替她说出还不敢承认的话",
        "axis": "speak",
        "motif": "折诗",
        "sound": "paper",
        "memory": "她把诗留给他，相信文字能穿过停电后的黑暗。",
        "confirmation": "纸被折了四次，刚好能藏进他的工具盒。",
        "nearEcho": "男生后来每次修放映机，都先把那张折诗从工具盒里取出来，放到不会沾上机油的地方。",
        "farEcho": "十三年后，他没有背诵诗句，只说自己一直记得纸被折过的方向。",
        "endingFragment": "你让那首没有署名的诗留下。它没有替他们找到出口，却让一句未说完的话抵达了另一个人。",
        "revisitEcho": "旧工具盒里，多了一张沿折痕发白的诗页。"
      },
      {
        "id": "kiss",
        "label": "主动吻他",
        "detail": "在电影重新亮起前先靠近一步",
        "axis": "keep",
        "motif": "照片",
        "sound": "photo",
        "memory": "停电的夜里，她先吻了他。",
        "confirmation": "电影还没有恢复，他们已经有了一段只属于黑暗的画面。",
        "nearEcho": "此后每次停电，男生都会下意识伸手找她；女生总比他早半步碰到那只手。",
        "farEcho": "咖啡馆的灯闪了一下，他们都抬起头，却没有再靠近。",
        "endingFragment": "你留住了停电时的那个吻。它没有要求后来的人生作证，只证明他们曾经毫不犹豫地靠近。",
        "revisitEcho": "黑暗里，两只手再次先于语言找到彼此。"
      },
      {
        "id": "leave",
        "label": "先行离开",
        "detail": "把心动收好，给自己一个夜晚",
        "axis": "survive",
        "motif": "电影票",
        "sound": "ticket",
        "memory": "她先走下楼梯，脚步很稳，心跳不是。",
        "confirmation": "第二天，她仍比约定早到了十分钟。",
        "nearEcho": "那以后女生总会提前确认出口，也总会在确认安全后第一个回来。",
        "farEcho": "重逢时，她先看见咖啡馆的后门；确认出口以后，才允许自己认真看他。",
        "endingFragment": "你保留了她先离开的能力。那不是拒绝，而是她很早就学会的事：勇气有时需要一条看得见的退路。",
        "revisitEcho": "她记住了出口，也记住了自己第二天仍然回来。"
      }
    ]
  },
  {
    "id": "echo-one",
    "kind": "echo",
    "chapter": "chapter1",
    "chapterLabel": "后来 · 德黑兰的夜晚",
    "place": "雨、屋顶与一台旧放映机",
    "art": "/art-v3/tehran-rooftop.png",
    "artFocus": "close",
    "object": "poem",
    "body": [
      "他们在屋顶分石榴，在雨里共用一把伞。风掀起伞沿时，女生抓住伞柄说：“别松手。”男生握紧伞柄，带她绕开屋檐下漏水的那一段。"
    ]
  },
  {
    "id": "promise",
    "kind": "narrative",
    "chapter": "chapter1",
    "chapterLabel": "第一章 · 革命街上的恋人",
    "place": "毕业照那天",
    "art": "/art-v5/graduation-photo-day.png",
    "canonicalPhoto": "/art-v5/canonical-graduation-photo.png",
    "object": "photo",
    "paidDialogueId": "paid-photo-developing",
    "chapterEnd": "chapter1",
    "rewardId": "chapter1",
    "body": [
      "摄影师问：“照片要冲两张吗？”女生说两张。快门按下时，所有人看着镜头，他们隔着人群看彼此。后来，他们冲洗了两张同版照片：女生带走一张，男生把另一张夹进诗集。",
      "男生收好其中一张，又收起复健预约单。父亲中风后，维修铺、药单和账本都在等他；女生第一次明白，他口中的“留下”不只有理想。"
    ]
  },
  {
    "id": "chapter-two",
    "kind": "chapter",
    "chapter": "chapter2",
    "chapterLabel": "第二章",
    "place": "知识变成证据",
    "year": "德黑兰 · 2009",
    "art": "/art-v4/student-publication-room.png",
    "body": [
      "他们曾用文字寻找出口。后来，文字先替权力找到了他们。"
    ]
  },
  {
    "id": "publication",
    "kind": "narrative",
    "chapter": "chapter2",
    "chapterLabel": "第二章 · 知识变成证据",
    "place": "学生宿舍 / 大学广场",
    "art": "/art-v4/student-publication-room.png",
    "object": "list",
    "progressive": true,
    "interactionIds": ["publication-clues"],
    "body": [
      "刊物最初只写电影、诗和女性生活。玛兹雅校对时，总用蓝铅笔画一颗小太阳。后来，他们报道了三名失踪学生，校园随即从里面锁上。",
      "玛兹雅当夜被带走，去向不明。第二天，学校叫女生去问话：谁和你一起做了刊物？"
    ]
  },
  {
    "id": "choice-two",
    "kind": "choice",
    "chapter": "chapter2",
    "chapterLabel": "第二次保存",
    "place": "大学纪律委员会",
    "art": "/art-v4/dorm-search-night.png",
    "body": [
      "调查者把三份刊物推到女生面前：“谁和你一起做的？”她必须决定是否告发同伴。"
    ],
    "choiceId": "choice-two",
    "interactionIds": ["names-decision"],
    "revisitBody": [
      "调查者仍在追问同一个问题：谁和你一起做的？这一次，她可以重新决定是否告发同伴。"
    ],
    "choices": [
      {
        "id": "reporter",
        "label": "只承认自己",
        "detail": "承认自己参与刊物，但不提供任何同伴姓名",
        "axis": "speak",
        "motif": "供词",
        "sound": "paper",
        "memory": "她只说自己的事，不替任何人作证。",
        "confirmation": "记录员追问三次，她三次重复同一句。",
        "nearEcho": "纪律委员会拿着已有材料追问同伴，女生只承认自己的文章。处分照样落下。",
        "farEcho": "男生翻到夹着处分通知的书页，仍记得她当年把每一句供词的主语都写成“我”。",
        "endingFragment": "你让她只承认自己的部分。她没有替同伴作证，也没有因此逃过处分。",
        "revisitEcho": "调查者换了三种问法，她只用“我”回答。"
      },
      {
        "id": "book",
        "label": "拒绝告发",
        "detail": "一个名字也不说，让沉默保护同伴",
        "axis": "keep",
        "motif": "诗集",
        "sound": "paper",
        "memory": "她拒绝指认任何同伴，把沉默留在记录里。",
        "confirmation": "房间里只剩钟表声。",
        "nearEcho": "问话记录写着“拒绝回答”。学校把沉默也算成了证据。",
        "farEcho": "十三年后，诗集里仍夹着那张处分通知；“拒绝回答”四个字已经发黄。",
        "endingFragment": "你让她拒绝告发。沉默没有撤销处分，却把同伴的名字留在她自己的记忆里。",
        "revisitEcho": "记录停在空白处，处分通知后来被夹进诗集。"
      },
      {
        "id": "burn",
        "label": "说出名字",
        "detail": "提供调查者追问的姓名，换取减轻处理",
        "axis": "survive",
        "motif": "笔迹",
        "sound": "ash",
        "memory": "她说出了三个名字，希望学校减轻处理。",
        "confirmation": "笔尖停下时，她没有抬头。",
        "nearEcho": "处理没有真正减轻。她第一次知道，妥协也可能什么都换不来。",
        "farEcho": "诗集里夹着处分通知，供词栏有三个被划过的名字。男生没有替她解释。",
        "endingFragment": "你让她说出三个调查者早已圈出的名字。处理没有减轻，这个动作也没有被结局原谅或定罪。",
        "revisitEcho": "三个名字落在纸上，处理决定仍然没有变。"
      }
    ]
  },
  {
    "id": "echo-two",
    "kind": "echo",
    "chapter": "chapter2",
    "chapterLabel": "后来 · 纪律委员会",
    "place": "没有提高声音的问话",
    "art": "/art-v3/discipline-committee.png",
    "artFocus": "desk",
    "object": "list",
    "interactionIds": ["discipline-record"],
    "body": [
      "调查的人把刊物、电影字幕和读书会记录依次推到女生面前。玛兹雅六个月后获释，再也没有回到大学。后来，她在设拉子一家儿童图书馆工作；修补过的借阅卡右下角，仍有蓝铅笔画的小太阳。"
    ]
  },
  {
    "id": "after-gate",
    "kind": "narrative",
    "chapter": "chapter2",
    "chapterLabel": "第二章 · 知识变成证据",
    "place": "大学铁门外",
    "art": "/art-v4/university-gate-expulsion.png",
    "paidDialogueId": "paid-lab-door",
    "chapterEnd": "chapter2",
    "rewardId": "chapter2",
    "body": [
      "女生失去继续深造的资格，出版社撤回工作邀请。实验楼的门合上前，男生往前半步，又停住。",
      "铁门外，女生看见他胸前还挂着实验室门卡，自己的名字却已从学生系统里消失。世界没有结束。它只是变窄了。"
    ]
  },
  {
    "id": "chapter-three",
    "kind": "chapter",
    "chapter": "chapter3",
    "chapterLabel": "第三章",
    "place": "只有一个人能够离开",
    "year": "德黑兰 · 2010",
    "art": "/art-v3/tehran-airport-departure.png",
    "body": [
      "出租屋钥匙落在桌子中央，护照申请压在另一边。两个人各自伸手，碰到的是不同的东西。"
    ]
  },
  {
    "id": "small-room",
    "kind": "montage",
    "chapter": "chapter3",
    "chapterLabel": "蒙太奇 · 出租屋",
    "place": "一段越来越具体的共同生活",
    "art": "/art-v3/tehran-rental-room.png",
    "object": "ticket",
    "interactionIds": ["departure-packing"],
    "beats": [
      "女生白天翻译软件说明书，夜里给盗版电影配字幕。",
      "男生替邻居修电脑，晚上再去父亲的维修铺对账。",
      "停电后，他们点蜡烛读诗。房租、药费和没有回音的护照申请也摊在烛光里。"
    ]
  },
  {
    "id": "one-year",
    "kind": "narrative",
    "chapter": "chapter3",
    "chapterLabel": "第三章 · 只有一个人能够离开",
    "place": "出租屋 · 凌晨",
    "art": "/art-v3/tehran-rental-room.png",
    "progressive": true,
    "speaker": "女生与男生",
    "body": [
      "“如果一年以后什么也没有改变呢？”男生看着父亲复健预约单：“那就再等一年。我不能让母亲一个人守着店，也不能让米拉德退学去接我的班。”",
      "女生把护照申请收回信封：“你留下，会继续是你自己。我留下，只会越来越不像我。”"
    ]
  },
  {
    "id": "kamran",
    "kind": "narrative",
    "chapter": "chapter3",
    "chapterLabel": "第三章 · 只有一个人能够离开",
    "place": "圣何塞 / 德黑兰",
    "art": "/art-v4/video-call-kamran.png",
    "object": "email",
    "paidDialogueId": "paid-marriage-truth",
    "body": [
      "姨妈介绍的卡姆兰把镜头转向堆满纸箱的客厅。他在软件外包公司工作，周末拍湾区空荡的停车场，自己冲洗黑白照片。“我知道你来找我的原因。只要我们都认真对待这段婚姻，我可以帮你离开。”",
      "通话结束前，卡姆兰把一张接触印样举到镜头前，请她替摄影投稿选一格。女生指出雾里的路灯压住了人物；他当场划掉那张，留下她选的空停车场。第二天，女生主动给姨妈回电话，要求先看全部手续，也要求婚后继续工作。三周后，她寄出第一份表格。"
    ]
  },
  {
    "id": "choice-three",
    "kind": "choice",
    "chapter": "chapter3",
    "chapterLabel": "第三次保存",
    "place": "德黑兰屋顶 · 最后一夜",
    "art": "/art-v4/final-rooftop-night.png",
    "body": [
      "手续已经推进，机票已经买好，卡姆兰的名字就在文件信封上。离开无法再被一句话取消；她仍要决定怎样把它告诉男生。"
    ],
    "choiceId": "choice-three",
    "interactionIds": ["last-night-truth"],
    "revisitBody": [
      "航班与手续已经确定。重剪不取消离开，只决定她把什么留在最后一夜。"
    ],
    "choices": [
      {
        "id": "truth",
        "label": "把一切一次说完",
        "detail": "把卡姆兰、婚姻、机票、害怕和仍然爱他一次说完",
        "axis": "speak",
        "motif": "未寄出的信",
        "sound": "paper",
        "memory": "她把最难听的真话留给了最爱的人。",
        "confirmation": "真话没有使夜晚更轻，但没有留下猜测。",
        "nearEcho": "国际出发大厅里，男生没有追问卡姆兰。他只是把她行李箱松开的搭扣重新扣好，然后退回大厅时钟下面。",
        "farEcho": "绿灯前，男生没有再问卡姆兰是谁；那个名字早已在最后一夜说完。",
        "endingFragment": "你让婚姻、恐惧和爱情同时被说出。真相没有挽留任何人，却使他们不必用余生猜测那场离开的名字。",
        "revisitEcho": "出发大厅的沉默里，不再藏着一个未被说出的名字。"
      },
      {
        "id": "escape",
        "label": "再问一条共同的路",
        "detail": "先说清卡姆兰，再问男生是否愿意一起寻找另一条路",
        "axis": "keep",
        "motif": "两张车票",
        "sound": "ticket",
        "memory": "她最后问了一次，而他的沉默就是回答。",
        "confirmation": "城市很大，却没有一条他们共同的出口。",
        "nearEcho": "男生赶到机场时仍带着两张旧公交票，像是误拿了某个本来可以成真的未来。",
        "farEcho": "绿灯前，男生把手从外套口袋里抽出来；那两张旧公交票仍夹在诗集末页。",
        "endingFragment": "你让她最后一次伸手要一个共同未来。男生没有接住，但那次请求使他们都无法把分离伪装成误会。",
        "revisitEcho": "诗集末页，多了两张没能把他们带到同一个出口的公交票。"
      },
      {
        "id": "conceal",
        "label": "只说航班已经确定",
        "detail": "只说航班已经确定，把卡姆兰的名字留在信封里",
        "axis": "survive",
        "motif": "行李牌",
        "sound": "ticket",
        "memory": "她省略了婚姻，把最锋利的部分留给自己。",
        "confirmation": "她先确认了航班和登机口，才允许自己哭。",
        "nearEcho": "安检口前男生问还有没有别的事。女生握紧行李牌，说没有。登机广播仍准时响起。",
        "farEcho": "路口，她先说卡姆兰正在等她；十三年前留在信封里的名字终于抵达街上。",
        "endingFragment": "你让她保留了最后一点能继续行动的体面。隐瞒留下伤口，也让她在那个早晨没有失去离开的力气。",
        "revisitEcho": "行李牌上的目的地清楚，告别里的原因仍然空白。"
      }
    ]
  },
  {
    "id": "echo-three",
    "kind": "echo",
    "chapter": "chapter3",
    "chapterLabel": "后来 · 德黑兰国际机场",
    "place": "国际出发 · 天亮以前",
    "art": "/art-v4/airport-clock-goodbye.png",
    "artFocus": "airport",
    "object": "ticket",
    "interactionIds": ["airport-goodbye"],
    "chapterEnd": "chapter3",
    "rewardId": "chapter3",
    "body": [
      "男生发来一条迟到的信息：“我到了。”女生抬头，他正站在大厅时钟下面。",
      "他替她扣紧行李箱松开的搭扣，没有请她留下。登机广播开始念她的航班。"
    ]
  },
  {
    "id": "chapter-four",
    "kind": "chapter",
    "chapter": "chapter4",
    "chapterLabel": "第四章",
    "place": "两个城市",
    "year": "圣何塞 / 德黑兰 · 2011—2021",
    "art": "/art-v5/san-jose-arrival-2011.png",
    "body": [
      "女生的飞机落地时，德黑兰的维修铺刚拉下卷帘门。两只钟从此显示不同的早晨。"
    ]
  },
  {
    "id": "two-cities",
    "kind": "montage",
    "chapter": "chapter4",
    "chapterLabel": "蒙太奇 · 两个城市",
    "place": "各自成立的生活",
    "art": "/art-v4/localization-office.png",
    "arts": [
      "/art-v4/localization-office.png",
      "/art-v4/maryam-telescope-rooftop.png",
      "/art-v3/san-jose-apartment.png"
    ],
    "interactionIds": ["dual-city-objects"],
    "paidDialogueId": "paid-two-cities-choice",
    "beats": [
      "女生在圣何塞落地，给卡姆兰发：“航班落地了。我在取行李。”白天她检查波斯语界面；晚上卡姆兰冲洗停车场的黑白照片。她替底片写波斯语编号，他按她选的光线重新放大。",
      "玛丽亚姆把流星观测表铺在男生的实验记录旁，教他用误差范围重排数据；他据此找出一组坏传感器。后来，男生用实验室废弃齿轮替她修好望远镜跟踪架，她拍下第一张完整的流星轨迹。",
      "他们各自成家，也把笑话、坏脾气和真正感兴趣的事带进眼前的关系。邮件从一页变成一段，最后剩下一句：革命街上的旧书店关门了。"
    ]
  },
  {
    "id": "email",
    "kind": "resonance",
    "chapter": "chapter4",
    "chapterLabel": "第四章 · 没有回复的邮件",
    "place": "圣何塞 · 凌晨",
    "art": "/art-v4/email-delete-night.png",
    "artFocus": "screen",
    "object": "email",
    "resonanceId": "email",
    "interactionIds": ["email-draft"],
    "revisitBody": [
      "光标仍在空白回复框里闪。重剪只改变她写下、又亲手删去的那一句。"
    ],
    "resonances": [
      {
        "id": "basement",
        "label": "“我记得地下室的味道。”",
        "detail": "写下最具体的那一晚",
        "motif": "删除键",
        "sound": "email",
        "echo": "光标停在“地下室的味道”后面。她点下删除，输入框重新变空。",
        "endingFragment": "她曾写下地下室潮湿的纸张和热灯泡气味，后来删掉了；重逢时，那气味仍先于对白回来。",
        "confirmation": "点下删除前，光标又闪了两次。"
      },
      {
        "id": "book",
        "label": "“那本诗集还在吗？”",
        "detail": "问一个她其实害怕知道答案的问题",
        "motif": "邮件草稿",
        "sound": "email",
        "echo": "问题写完以后，她没有按发送。她不确定自己想问的是书，还是书里仍被保管的那些人。",
        "endingFragment": "她曾在邮件里问诗集是否还在，又删掉了。十三年后，男生用把书放到桌上的动作回答了她。",
        "confirmation": "她在问号后停了一分钟。"
      },
      {
        "id": "well",
        "label": "“我现在过得很好。”",
        "detail": "写下一句既真实又不完整的话",
        "motif": "未发送",
        "sound": "email",
        "echo": "她看着“很好”两个字，承认生活确实已经有了重量，然后删掉整句。",
        "endingFragment": "她曾想告诉他自己过得很好。那不是炫耀，也不是谎言；只是完整生活无法被压进一封旧情人的邮件。",
        "confirmation": "这句话是真的，只是不完整。"
      }
    ],
    "body": [
      "女生打开回复框。卡姆兰在客厅整理新洗出的照片，没有催她睡。她写下一句话，最后仍会删除。十三年后，她会先想起其中的某个词。"
    ]
  },
  {
    "id": "last-email",
    "kind": "narrative",
    "chapter": "chapter4",
    "chapterLabel": "第四章 · 没有回复的邮件",
    "place": "删除以后",
    "art": "/art-v4/email-delete-night.png",
    "object": "email",
    "interactionIds": ["receipt-memory-combination"],
    "chapterEnd": "chapter4",
    "rewardId": "chapter4",
    "body": [
      "屏幕重新变成空白。卡姆兰把一张刚洗好的照片递给她：雾里的高速公路没有一辆车。“像不像你总说的革命街？”女生说不像，然后把照片贴到了冰箱上。"
    ]
  },
  {
    "id": "chapter-five",
    "kind": "chapter",
    "chapter": "chapter5",
    "chapterLabel": "第五章",
    "place": "伊斯坦布尔重逢",
    "year": "十三年后",
    "art": "/art-v2/istanbul-cafe.png",
    "body": [
      "门外下着雨。女生先放好照片，男生抱着诗集推门。他们说完你好，再把十三年分成几件可以放上桌的东西。"
    ]
  },
  {
    "id": "gaze",
    "kind": "resonance",
    "chapter": "chapter5",
    "chapterLabel": "第五章 · 重逢",
    "place": "卡拉柯伊 · 老咖啡馆",
    "art": "/art-v5/istanbul-reunion-aged.png",
    "artFocus": "table",
    "object": "book",
    "resonanceId": "gaze",
    "interactionIds": ["reunion-gaze"],
    "revisitBody": [
      "门已经推开。你可以重新决定十三年的时间先落进哪一个取景框。"
    ],
    "resonances": [
      {
        "id": "hands",
        "label": "先看他的白发与手",
        "detail": "辨认时间留在一个人身上的地方",
        "motif": "手与白发",
        "sound": "photo",
        "echo": "她先认出他端茶时仍会用拇指摩挲杯沿，只是手背多了细纹。",
        "endingFragment": "最后的镜头停在他放开茶杯的手上。亲密感没有消失，只是失去了继续使用的权利。",
        "confirmation": "十三年先落在指节和鬓角。"
      },
      {
        "id": "book",
        "label": "先看发黄的诗集",
        "detail": "确认那些被保管的纸页",
        "motif": "发黄书页",
        "sound": "paper",
        "echo": "她先看见诗集书脊上的裂口，才抬头看男生。",
        "endingFragment": "最后的镜头越过人群，停在他臂弯里的旧诗集上。被保存不等于能回去。",
        "confirmation": "书页的颜色比记忆更诚实。"
      },
      {
        "id": "clock",
        "label": "先看时钟与机场方向",
        "detail": "记住现实仍在等待",
        "motif": "站钟",
        "sound": "ticket",
        "echo": "她先确认去机场还有四十分钟，也看见男生手机上来自家人的未接来电。",
        "endingFragment": "最后的镜头停在绿灯和机场方向牌上。两个人都已经有人在现实生活里等待。",
        "confirmation": "四十分钟后，机场班车不会等她。"
      }
    ],
    "body": [
      "手机亮起：“我到了。”门被推开，雨水和热灯泡的气味一起进来。男生先说你好。",
      "“你过得好吗？”——“还可以。你呢？”——“也还可以。”他把诗集放在桌上。女生先把视线停在哪里？"
    ]
  },
  {
    "id": "book",
    "kind": "narrative",
    "chapter": "chapter5",
    "chapterLabel": "第五章 · 两张相同的照片",
    "place": "诗集与桌面",
    "art": "/art-v5/poetry-book-photo-close.png",
    "canonicalPhoto": "/art-v5/canonical-graduation-photo.png",
    "artFocus": "book",
    "object": "photo",
    "interactionIds": ["photo-pairing"],
    "paidDialogueId": "paid-reunion-hypothesis",
    "body": [
      "男生翻开诗集，里面是他保存的那张毕业照；桌上或女生包里，是她保存的另一张。两张照片来自同一次冲洗，边角却有了不同的磨损。",
      "他用指节压住要合上的书页，她按住自己的照片。十三年前那句“别松手”留在两处磨损之间。他们谈起玛兹雅、卡姆兰的底片和玛丽亚姆记录的流星。"
    ]
  },
  {
    "id": "crossroads",
    "kind": "narrative",
    "chapter": "chapter5",
    "chapterLabel": "终章 · 另一个故事",
    "place": "伊斯坦布尔街头",
    "art": "/art-v5/istanbul-crossroads-aged.png",
    "progressive": true,
    "speaker": "男生与女生",
    "interactionIds": ["final-crossroad"],
    "chapterEnd": "chapter5",
    "rewardId": "chapter5",
    "body": [
      "绿灯亮起。女生要去机场，男生要回酒店。他们站在路口，没有拥抱。",
      "“如果当年我跟你走了呢？”女生看着他：“那我们会有另一个故事。”",
      "人群涌来。他们走向不同方向，又在同一刻回头笑了一下。"
    ]
  }
];
export const revisitScenes: Scene[] = [
  {
    "id": "cut-one",
    "kind": "narrative",
    "chapter": "chapter1",
    "chapterLabel": "记忆剪辑 01",
    "place": "地下室停电以后",
    "art": "/art-v4/underground-projector-close.png",
    "body": [
      "旧胶片停在接吻、折诗和楼梯口之间。你可以沿用上轮，也可以重新剪下这一格。"
    ]
  },
  {
    "id": "choice-one",
    "kind": "choice",
    "chapter": "chapter1",
    "chapterLabel": "第一次保存",
    "place": "停电后的地下室",
    "art": "/art-v4/underground-projector-close.png",
    "body": [
      "“看不见画面，故事也不会消失。”停电还没结束。女生先做了什么？"
    ],
    "choiceId": "choice-one",
    "choices": [
      {
        "id": "poem",
        "label": "送他一首诗",
        "detail": "让纸替她说出还不敢承认的话",
        "axis": "speak",
        "motif": "折诗",
        "sound": "paper",
        "memory": "她把诗留给他，相信文字能穿过停电后的黑暗。",
        "confirmation": "纸被折了四次，刚好能藏进他的工具盒。",
        "nearEcho": "男生后来每次修放映机，都先把那张折诗从工具盒里取出来，放到不会沾上机油的地方。",
        "farEcho": "十三年后，他没有背诵诗句，只说自己一直记得纸被折过的方向。",
        "endingFragment": "你让那首没有署名的诗留下。它没有替他们找到出口，却让一句未说完的话抵达了另一个人。",
        "revisitEcho": "旧工具盒里，多了一张沿折痕发白的诗页。"
      },
      {
        "id": "kiss",
        "label": "主动吻他",
        "detail": "在电影重新亮起前先靠近一步",
        "axis": "keep",
        "motif": "照片",
        "sound": "photo",
        "memory": "停电的夜里，她先吻了他。",
        "confirmation": "电影还没有恢复，他们已经有了一段只属于黑暗的画面。",
        "nearEcho": "此后每次停电，男生都会下意识伸手找她；女生总比他早半步碰到那只手。",
        "farEcho": "咖啡馆的灯闪了一下，他们都抬起头，却没有再靠近。",
        "endingFragment": "你留住了停电时的那个吻。它没有要求后来的人生作证，只证明他们曾经毫不犹豫地靠近。",
        "revisitEcho": "黑暗里，两只手再次先于语言找到彼此。"
      },
      {
        "id": "leave",
        "label": "先行离开",
        "detail": "把心动收好，给自己一个夜晚",
        "axis": "survive",
        "motif": "电影票",
        "sound": "ticket",
        "memory": "她先走下楼梯，脚步很稳，心跳不是。",
        "confirmation": "第二天，她仍比约定早到了十分钟。",
        "nearEcho": "那以后女生总会提前确认出口，也总会在确认安全后第一个回来。",
        "farEcho": "重逢时，她先看见咖啡馆的后门；确认出口以后，才允许自己认真看他。",
        "endingFragment": "你保留了她先离开的能力。那不是拒绝，而是她很早就学会的事：勇气有时需要一条看得见的退路。",
        "revisitEcho": "她记住了出口，也记住了自己第二天仍然回来。"
      }
    ]
  },
  {
    "id": "revisit-echo-one",
    "kind": "revisitEcho",
    "chapter": "chapter1",
    "chapterLabel": "后来",
    "place": "这次改动如何抵达未来",
    "art": "/art-v4/graduation-photo-day.png",
    "choiceId": "choice-one",
    "choices": [
      {
        "id": "poem",
        "label": "送他一首诗",
        "detail": "让纸替她说出还不敢承认的话",
        "axis": "speak",
        "motif": "折诗",
        "sound": "paper",
        "memory": "她把诗留给他，相信文字能穿过停电后的黑暗。",
        "confirmation": "纸被折了四次，刚好能藏进他的工具盒。",
        "nearEcho": "男生后来每次修放映机，都先把那张折诗从工具盒里取出来，放到不会沾上机油的地方。",
        "farEcho": "十三年后，他没有背诵诗句，只说自己一直记得纸被折过的方向。",
        "endingFragment": "你让那首没有署名的诗留下。它没有替他们找到出口，却让一句未说完的话抵达了另一个人。",
        "revisitEcho": "旧工具盒里，多了一张沿折痕发白的诗页。"
      },
      {
        "id": "kiss",
        "label": "主动吻他",
        "detail": "在电影重新亮起前先靠近一步",
        "axis": "keep",
        "motif": "照片",
        "sound": "photo",
        "memory": "停电的夜里，她先吻了他。",
        "confirmation": "电影还没有恢复，他们已经有了一段只属于黑暗的画面。",
        "nearEcho": "此后每次停电，男生都会下意识伸手找她；女生总比他早半步碰到那只手。",
        "farEcho": "咖啡馆的灯闪了一下，他们都抬起头，却没有再靠近。",
        "endingFragment": "你留住了停电时的那个吻。它没有要求后来的人生作证，只证明他们曾经毫不犹豫地靠近。",
        "revisitEcho": "黑暗里，两只手再次先于语言找到彼此。"
      },
      {
        "id": "leave",
        "label": "先行离开",
        "detail": "把心动收好，给自己一个夜晚",
        "axis": "survive",
        "motif": "电影票",
        "sound": "ticket",
        "memory": "她先走下楼梯，脚步很稳，心跳不是。",
        "confirmation": "第二天，她仍比约定早到了十分钟。",
        "nearEcho": "那以后女生总会提前确认出口，也总会在确认安全后第一个回来。",
        "farEcho": "重逢时，她先看见咖啡馆的后门；确认出口以后，才允许自己认真看他。",
        "endingFragment": "你保留了她先离开的能力。那不是拒绝，而是她很早就学会的事：勇气有时需要一条看得见的退路。",
        "revisitEcho": "她记住了出口，也记住了自己第二天仍然回来。"
      }
    ]
  },
  {
    "id": "cut-two",
    "kind": "narrative",
    "chapter": "chapter2",
    "chapterLabel": "记忆剪辑 02",
    "place": "问话还没有结束",
    "art": "/art-v4/dorm-search-night.png",
    "body": [
      "玛兹雅被带走后去向不明。纪律委员会叫女生说出其他参与者的名字。"
    ]
  },
  {
    "id": "choice-two",
    "kind": "choice",
    "chapter": "chapter2",
    "chapterLabel": "第二次保存",
    "place": "大学纪律委员会",
    "art": "/art-v4/dorm-search-night.png",
    "body": [
      "调查者把三份刊物推到女生面前：“谁和你一起做的？”她必须决定是否告发同伴。"
    ],
    "choiceId": "choice-two",
    "choices": [
      {
        "id": "reporter",
        "label": "只承认自己",
        "detail": "承认自己参与刊物，但不提供任何同伴姓名",
        "axis": "speak",
        "motif": "供词",
        "sound": "paper",
        "memory": "她只说自己的事，不替任何人作证。",
        "confirmation": "记录员追问三次，她三次重复同一句。",
        "nearEcho": "纪律委员会拿着已有材料追问同伴，女生只承认自己的文章。处分照样落下。",
        "farEcho": "男生翻到夹着处分通知的书页，仍记得她当年把每一句供词的主语都写成“我”。",
        "endingFragment": "你让她只承认自己的部分。她没有替同伴作证，也没有因此逃过处分。",
        "revisitEcho": "调查者换了三种问法，她只用“我”回答。"
      },
      {
        "id": "book",
        "label": "拒绝告发",
        "detail": "一个名字也不说，让沉默保护同伴",
        "axis": "keep",
        "motif": "诗集",
        "sound": "paper",
        "memory": "她拒绝指认任何同伴，把沉默留在记录里。",
        "confirmation": "房间里只剩钟表声。",
        "nearEcho": "问话记录写着“拒绝回答”。学校把沉默也算成了证据。",
        "farEcho": "十三年后，诗集里仍夹着那张处分通知；“拒绝回答”四个字已经发黄。",
        "endingFragment": "你让她拒绝告发。沉默没有撤销处分，却把同伴的名字留在她自己的记忆里。",
        "revisitEcho": "记录停在空白处，处分通知后来被夹进诗集。"
      },
      {
        "id": "burn",
        "label": "说出名字",
        "detail": "提供调查者追问的姓名，换取减轻处理",
        "axis": "survive",
        "motif": "笔迹",
        "sound": "ash",
        "memory": "她说出了三个名字，希望学校减轻处理。",
        "confirmation": "笔尖停下时，她没有抬头。",
        "nearEcho": "处理没有真正减轻。她第一次知道，妥协也可能什么都换不来。",
        "farEcho": "诗集里夹着处分通知，供词栏有三个被划过的名字。男生没有替她解释。",
        "endingFragment": "你让她说出三个调查者早已圈出的名字。处理没有减轻，这个动作也没有被结局原谅或定罪。",
        "revisitEcho": "三个名字落在纸上，处理决定仍然没有变。"
      }
    ]
  },
  {
    "id": "revisit-echo-two",
    "kind": "revisitEcho",
    "chapter": "chapter2",
    "chapterLabel": "后来",
    "place": "这次改动如何抵达未来",
    "art": "/art-v4/university-gate-expulsion.png",
    "choiceId": "choice-two",
    "choices": [
      {
        "id": "reporter",
        "label": "只承认自己",
        "detail": "承认自己参与刊物，但不提供任何同伴姓名",
        "axis": "speak",
        "motif": "供词",
        "sound": "paper",
        "memory": "她只说自己的事，不替任何人作证。",
        "confirmation": "记录员追问三次，她三次重复同一句。",
        "nearEcho": "纪律委员会拿着已有材料追问同伴，女生只承认自己的文章。处分照样落下。",
        "farEcho": "男生翻到夹着处分通知的书页，仍记得她当年把每一句供词的主语都写成“我”。",
        "endingFragment": "你让她只承认自己的部分。她没有替同伴作证，也没有因此逃过处分。",
        "revisitEcho": "调查者换了三种问法，她只用“我”回答。"
      },
      {
        "id": "book",
        "label": "拒绝告发",
        "detail": "一个名字也不说，让沉默保护同伴",
        "axis": "keep",
        "motif": "诗集",
        "sound": "paper",
        "memory": "她拒绝指认任何同伴，把沉默留在记录里。",
        "confirmation": "房间里只剩钟表声。",
        "nearEcho": "问话记录写着“拒绝回答”。学校把沉默也算成了证据。",
        "farEcho": "十三年后，诗集里仍夹着那张处分通知；“拒绝回答”四个字已经发黄。",
        "endingFragment": "你让她拒绝告发。沉默没有撤销处分，却把同伴的名字留在她自己的记忆里。",
        "revisitEcho": "记录停在空白处，处分通知后来被夹进诗集。"
      },
      {
        "id": "burn",
        "label": "说出名字",
        "detail": "提供调查者追问的姓名，换取减轻处理",
        "axis": "survive",
        "motif": "笔迹",
        "sound": "ash",
        "memory": "她说出了三个名字，希望学校减轻处理。",
        "confirmation": "笔尖停下时，她没有抬头。",
        "nearEcho": "处理没有真正减轻。她第一次知道，妥协也可能什么都换不来。",
        "farEcho": "诗集里夹着处分通知，供词栏有三个被划过的名字。男生没有替她解释。",
        "endingFragment": "你让她说出三个调查者早已圈出的名字。处理没有减轻，这个动作也没有被结局原谅或定罪。",
        "revisitEcho": "三个名字落在纸上，处理决定仍然没有变。"
      }
    ]
  },
  {
    "id": "cut-three",
    "kind": "narrative",
    "chapter": "chapter3",
    "chapterLabel": "记忆剪辑 03",
    "place": "离开已经决定",
    "art": "/art-v4/airport-clock-goodbye.png",
    "body": [
      "手续和机票不会消失。你只能重新决定，最后一夜有哪些话被留下。"
    ]
  },
  {
    "id": "choice-three",
    "kind": "choice",
    "chapter": "chapter3",
    "chapterLabel": "第三次保存",
    "place": "德黑兰屋顶 · 最后一夜",
    "art": "/art-v4/final-rooftop-night.png",
    "body": [
      "手续已经推进，机票已经买好，卡姆兰的名字就在文件信封上。离开无法再被一句话取消；她仍要决定怎样把它告诉男生。"
    ],
    "choiceId": "choice-three",
    "choices": [
      {
        "id": "truth",
        "label": "把一切一次说完",
        "detail": "把卡姆兰、婚姻、机票、害怕和仍然爱他一次说完",
        "axis": "speak",
        "motif": "未寄出的信",
        "sound": "paper",
        "memory": "她把最难听的真话留给了最爱的人。",
        "confirmation": "真话没有使夜晚更轻，但没有留下猜测。",
        "nearEcho": "国际出发大厅里，男生没有追问卡姆兰。他只是把她行李箱松开的搭扣重新扣好，然后退回大厅时钟下面。",
        "farEcho": "绿灯前，男生没有再问卡姆兰是谁；那个名字早已在最后一夜说完。",
        "endingFragment": "你让婚姻、恐惧和爱情同时被说出。真相没有挽留任何人，却使他们不必用余生猜测那场离开的名字。",
        "revisitEcho": "出发大厅的沉默里，不再藏着一个未被说出的名字。"
      },
      {
        "id": "escape",
        "label": "再问一条共同的路",
        "detail": "先说清卡姆兰，再问男生是否愿意一起寻找另一条路",
        "axis": "keep",
        "motif": "两张车票",
        "sound": "ticket",
        "memory": "她最后问了一次，而他的沉默就是回答。",
        "confirmation": "城市很大，却没有一条他们共同的出口。",
        "nearEcho": "男生赶到机场时仍带着两张旧公交票，像是误拿了某个本来可以成真的未来。",
        "farEcho": "绿灯前，男生把手从外套口袋里抽出来；那两张旧公交票仍夹在诗集末页。",
        "endingFragment": "你让她最后一次伸手要一个共同未来。男生没有接住，但那次请求使他们都无法把分离伪装成误会。",
        "revisitEcho": "诗集末页，多了两张没能把他们带到同一个出口的公交票。"
      },
      {
        "id": "conceal",
        "label": "只说航班已经确定",
        "detail": "只说航班已经确定，把卡姆兰的名字留在信封里",
        "axis": "survive",
        "motif": "行李牌",
        "sound": "ticket",
        "memory": "她省略了婚姻，把最锋利的部分留给自己。",
        "confirmation": "她先确认了航班和登机口，才允许自己哭。",
        "nearEcho": "安检口前男生问还有没有别的事。女生握紧行李牌，说没有。登机广播仍准时响起。",
        "farEcho": "路口，她先说卡姆兰正在等她；十三年前留在信封里的名字终于抵达街上。",
        "endingFragment": "你让她保留了最后一点能继续行动的体面。隐瞒留下伤口，也让她在那个早晨没有失去离开的力气。",
        "revisitEcho": "行李牌上的目的地清楚，告别里的原因仍然空白。"
      }
    ]
  },
  {
    "id": "revisit-echo-three",
    "kind": "revisitEcho",
    "chapter": "chapter3",
    "chapterLabel": "后来",
    "place": "这次改动如何抵达未来",
    "art": "/art-v4/airport-clock-goodbye.png",
    "choiceId": "choice-three",
    "choices": [
      {
        "id": "truth",
        "label": "把一切一次说完",
        "detail": "把卡姆兰、婚姻、机票、害怕和仍然爱他一次说完",
        "axis": "speak",
        "motif": "未寄出的信",
        "sound": "paper",
        "memory": "她把最难听的真话留给了最爱的人。",
        "confirmation": "真话没有使夜晚更轻，但没有留下猜测。",
        "nearEcho": "国际出发大厅里，男生没有追问卡姆兰。他只是把她行李箱松开的搭扣重新扣好，然后退回大厅时钟下面。",
        "farEcho": "绿灯前，男生没有再问卡姆兰是谁；那个名字早已在最后一夜说完。",
        "endingFragment": "你让婚姻、恐惧和爱情同时被说出。真相没有挽留任何人，却使他们不必用余生猜测那场离开的名字。",
        "revisitEcho": "出发大厅的沉默里，不再藏着一个未被说出的名字。"
      },
      {
        "id": "escape",
        "label": "再问一条共同的路",
        "detail": "先说清卡姆兰，再问男生是否愿意一起寻找另一条路",
        "axis": "keep",
        "motif": "两张车票",
        "sound": "ticket",
        "memory": "她最后问了一次，而他的沉默就是回答。",
        "confirmation": "城市很大，却没有一条他们共同的出口。",
        "nearEcho": "男生赶到机场时仍带着两张旧公交票，像是误拿了某个本来可以成真的未来。",
        "farEcho": "绿灯前，男生把手从外套口袋里抽出来；那两张旧公交票仍夹在诗集末页。",
        "endingFragment": "你让她最后一次伸手要一个共同未来。男生没有接住，但那次请求使他们都无法把分离伪装成误会。",
        "revisitEcho": "诗集末页，多了两张没能把他们带到同一个出口的公交票。"
      },
      {
        "id": "conceal",
        "label": "只说航班已经确定",
        "detail": "只说航班已经确定，把卡姆兰的名字留在信封里",
        "axis": "survive",
        "motif": "行李牌",
        "sound": "ticket",
        "memory": "她省略了婚姻，把最锋利的部分留给自己。",
        "confirmation": "她先确认了航班和登机口，才允许自己哭。",
        "nearEcho": "安检口前男生问还有没有别的事。女生握紧行李牌，说没有。登机广播仍准时响起。",
        "farEcho": "路口，她先说卡姆兰正在等她；十三年前留在信封里的名字终于抵达街上。",
        "endingFragment": "你让她保留了最后一点能继续行动的体面。隐瞒留下伤口，也让她在那个早晨没有失去离开的力气。",
        "revisitEcho": "行李牌上的目的地清楚，告别里的原因仍然空白。"
      }
    ]
  }
];

/**
 * 场景里保留的旧副本仅用于历史存档兼容；运行时始终挂接中央契约，
 * 避免正文、剪辑室与结局各维护一份会漂移的选择文案。
 */
for (const scene of [...scenes, ...revisitScenes]) {
  if (scene.choiceId && memoryContracts[scene.choiceId]) {
    scene.choices = memoryContracts[scene.choiceId];
  }
  if (scene.resonanceId && resonanceContracts[scene.resonanceId]) {
    scene.resonances = resonanceContracts[scene.resonanceId];
  }
}

export type FutureEchoRoute = {
  source: "choice" | "resonance";
  /** kind mirrors source for page-level compatibility with V4 saves/components. */
  kind?: "choice" | "resonance";
  id: string;
  field: "farEcho";
};

/** 每个场景最多兑现两条回响；视线本身只进入最终镜头，不在下一幕复述。 */
export const futureEchoRoutes: Record<string, FutureEchoRoute[]> = {
  "gaze": [
    { source: "choice", kind: "choice", id: "choice-one", field: "farEcho" },
    { source: "resonance", kind: "resonance", id: "email", field: "farEcho" },
  ],
  "book": [
    { source: "resonance", kind: "resonance", id: "photo", field: "farEcho" },
    { source: "choice", kind: "choice", id: "choice-two", field: "farEcho" },
  ],
  "crossroads": [
    { source: "choice", kind: "choice", id: "choice-three", field: "farEcho" },
  ],
};

export const choiceIds = [
  "choice-one",
  "choice-two",
  "choice-three"
];
export const resonanceIds = [
  "photo",
  "email",
  "gaze"
];
export const endings: Record<EndingKey,{title:string;reveal:string;body:string;coda:string}> = {
  "speak": {
    "title": "你让未说出口的事抵达",
    "reveal": "说出 · 理想的前身",
    "body": "你反复选择把诗、责任和真相交给另一个人。说出没有改写结局，却拒绝让沉默成为唯一版本。",
    "coda": "话语不能使两条路重合，但能让分岔不再被误认成遗忘。"
  },
  "keep": {
    "title": "你让被爱过的证据留下",
    "reveal": "留住 · 爱情的形状",
    "body": "你反复选择靠近、保存和请求共同未来。留住不是占有；它只是让已经发生的亲密不被后来的人生否认。",
    "coda": "被保存的东西不要求人回去，只要求人承认它曾经存在。"
  },
  "survive": {
    "title": "你让她有力气走到明天",
    "reveal": "活下去 · 生存的动作",
    "body": "你反复选择出口、安全和能继续行动的体面。活下去并不比理想低，也不比爱情轻；它让人仍有能力承担自己的选择。",
    "coda": "离开不是胜利，但它把明天重新交回她手里。"
  },
  "mixed": {
    "title": "你让三种记忆同时留下",
    "reveal": "说出 · 留住 · 活下去",
    "body": "三种动作在这一轮各出现一次：说出没有取消留住，留住也没有否定继续生活。它们并列，而不是互相裁决。",
    "coda": "她没有让一种记忆替另外两种作证。"
  }
};
export const unchosenFragments = [
  {
    "optionId": "poem",
    "text": "有一版记忆里，电影恢复以前没有人靠近；只有工具盒里多了一道纸的折痕。"
  },
  {
    "optionId": "burn",
    "text": "有一版记忆里，她说出三个调查者早已圈出的名字；处分仍然没有减轻。"
  },
  {
    "optionId": "escape",
    "text": "有一版记忆里，两张公交票一直夹在诗集末页，没有把他们带到同一个出口。"
  },
  {
    "optionId": "well",
    "text": "有一版记忆里，邮件只写了“我很好”，然后整句被删除。"
  }
];
