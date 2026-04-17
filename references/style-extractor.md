# 风格提取器 v3.0

## 使用场景

在【模式 D：建库/更新】中，对用户提供的样本文章执行风格提取时调用此文件。
按照下方提示词对样本执行分析，输出结构化 JSON 风格指纹。

---

## 提取提示词

请对以下文本进行深度风格解析，提取**可跨领域迁移的写作行为规则**，而非内容层面的具体表达。

### 分析原则

- **迁移性优先**：提取的所有特征必须能应用于任意主题的文本生成，主动过滤内容专有词汇（人名、地名、学科术语、机构名等）
- **行为化描述**：风格特征以"写作行为"而非"观察印象"的方式表述，每条描述应能直接指导生成
- **边界意识**：不只描述"是什么风格"，同样描述"明显不是什么风格"
- **锚点量化**：数值评分必须附带行为锚点说明，避免模糊评级

### 迁移性自检（提取完成后对每条特征执行）

> "如果把这条规则用于一篇完全不同领域的文章，它还成立吗？"
> 若不成立 → 说明提取了内容而非风格 → 重新抽象后替换。

---

## 输出格式

```json
{
    "style_summary": "用一句话概括：这是一种怎样的写作行为模式（而非内容描述）",

    "style_boundaries": {
        "core_invariants": [
            "无论何种主题和文体，始终保持的写作特征",
            "另一条跨文体不变量"
        ],
        "forbidden_patterns": [
            "任何情况下都不会出现的写法",
            "另一条绝对禁忌"
        ],
        "domain_firewall": "需主动过滤的领域专有词汇范围及替换策略"
    },

    "language_texture": {
        "vocabulary_density": {
            "score": "1-5",
            "behavioral_anchor": "对应的具体写作行为"
        },
        "sentence_preference": {
            "dominant_patterns": ["主导句式1及其使用场景", "主导句式2及其使用场景"],
            "length_tendency": {
                "score": "1-5（1=极短促，5=绵长）",
                "behavioral_anchor": "句长控制的具体行为"
            },
            "complexity": {
                "score": "1-5",
                "behavioral_anchor": "句法复杂度的操作描述"
            }
        },
        "word_choice": {
            "formality": {
                "score": "1-5",
                "behavioral_anchor": "用词正式度的操作描述"
            },
            "abstraction": {
                "score": "1-5",
                "behavioral_anchor": "抽象度处理方式"
            },
            "characteristic_word_types": ["特征词类描述（描述类型而非具体词汇）"],
            "avoided_expressions": ["规避的表达类型"]
        },
        "rhetoric_toolkit": [
            {"type": "修辞类型", "usage_pattern": "使用场景和频率"}
        ],
        "language_register": "书面化/口语化程度及混用规律"
    },

    "generative_rules": {
        "sentence_construction": "造句时的底层习惯",
        "paragraph_opening": "段落开头的惯用策略",
        "paragraph_closing": "段落收束的惯用方式",
        "rhythm_control": "节奏控制的具体操作",
        "abstraction_grounding": "处理抽象内容时的具象化策略",
        "complexity_handling": "遇到复杂论证时的拆解方式",
        "avoided_constructions": ["明显不会这样写的句式或结构模式"]
    },

    "structure_awareness": {
        "layout_strategy": {
            "type": "整体布局类型",
            "behavioral_anchor": "布局决策的具体操作"
        },
        "paragraph_rhythm": {
            "length_pattern": "段落长度分布规律",
            "length_variation": "段落长度变化的节奏逻辑"
        },
        "transition_style": {
            "type": "过渡方式",
            "behavioral_anchor": "过渡处理的具体操作"
        },
        "information_density": {
            "score": "1-5",
            "behavioral_anchor": "信息密度的控制策略"
        }
    },

    "narrative_strategy": {
        "perspective": "叙事视角类型及其稳定性",
        "detail_selection": {
            "preference": "细节偏好类型",
            "granularity": {
                "score": "1-5",
                "behavioral_anchor": "细节颗粒度的操作描述"
            }
        },
        "distance_control": "叙事距离的设定及变化规律",
        "example_usage": "案例/例证的使用策略"
    },

    "emotional_texture": {
        "intensity": {
            "score": "1-5",
            "behavioral_anchor": "情绪浓度的具体体现"
        },
        "expression_mode": "情感表达方式",
        "restraint_mechanism": "克制情绪的具体手法",
        "tonal_baseline": "文章的基础情感基调",
        "emotional_range": "情感波动的幅度和触发条件"
    },

    "thinking_pattern": {
        "logic_type": "主导逻辑类型",
        "depth_level": {
            "score": "1-5",
            "behavioral_anchor": "思考深度的操作表现"
        },
        "progression_rhythm": "论证推进的节奏特征",
        "reasoning_style": "论证风格",
        "uncertainty_handling": "处理不确定性或复杂议题的方式"
    },

    "value_coordinates": {
        "stance_tendency": "立场倾向的呈现方式",
        "focus_areas": ["持续关注的议题类型（用抽象描述）"],
        "avoidance_zones": ["倾向回避或轻描淡写的角度"],
        "implicit_values": "从写作行为中折射出的价值取向"
    },

    "interactive_posture": {
        "target_reader": "预设读者的能力预设和关系定位",
        "dialogue_distance": {
            "type": "对话距离类型",
            "behavioral_anchor": "对话距离的具体操作方式"
        },
        "persuasion_strategy": "说服策略类型及操作方式",
        "energy_transmission": "能量传递方式",
        "reader_assumption": "对读者知识背景的默认预设"
    }
}
```
