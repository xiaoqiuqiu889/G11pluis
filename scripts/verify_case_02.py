#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二案 YAML 校验脚本"""
import yaml
import glob
import os
import sys

CASE02_DIR = "D:/G1-ai-native/content/case_02_moscow_no_fairy_tale"

files = sorted(glob.glob(f"{CASE02_DIR}/**/*.yaml", recursive=True))
print(f"Found {len(files)} YAML files\n")

SCHEMA_REQUIRED = [
    "sceneId", "title", "era", "location", "required_anchors",
    "core_conflict", "allowed_beats", "forbidden_reveals",
    "max_turns", "total_action_budget", "legal_endings", "schemaVersion"
]

for f in files:
    name = os.path.basename(f)
    try:
        with open(f, "r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp)
        if "sceneId" in data:
            # 场景合同
            missing = [k for k in SCHEMA_REQUIRED if k not in data]
            sv = data.get("schemaVersion", "?")
            anchors = len(data.get("required_anchors", []))
            beats = len(data.get("allowed_beats", []))
            forb = len(data.get("forbidden_reveals", []))
            ends = len(data.get("legal_endings", []))
            m_echoes = data.get("mandatory_echoes", [])
            n_recall = data.get("npc_recall_lines", [])
            inv = data.get("investigatable_objects", [])
            cs = data.get("causal_seeds_extended", [])
            cast = data.get("cast", [])
            print(f"== {name} ==")
            print(f"  sceneId: {data['sceneId']}")
            print(f"  era: {data['era']} | schemaVersion: {sv}")
            print(f"  required_anchors: {anchors} | allowed_beats: {beats} | forbidden_reveals: {forb}")
            print(f"  legal_endings: {ends} | cast: {len(cast)}")
            print(f"  investigatable_objects: {len(inv)} | causal_seeds_extended: {len(cs)}")
            print(f"  mandatory_echoes: {len(m_echoes)} | npc_recall_lines: {len(n_recall)}")
            if missing:
                print(f"  !! missing schema fields: {missing}")
            else:
                print(f"  ✓ all 12 schema required fields present")
            # era 检查
            allowed_eras = ["pre_1911_qing","1911_1927_republic","1927_1937_nanjing_decade",
                            "1937_1945_war","1945_1949_civil_war","1949_1965_socialist_build",
                            "1966_1976_cultural_revolution","1977_1989_reform_early",
                            "1989_2000_boom","2000_2012_globalization","2012_present_ai_age",
                            "present","epilogue","2008","2011","2024","EPILOGUE"]
            if data["era"] not in allowed_eras:
                print(f"  !! era '{data['era']}' not in schema enum")
            else:
                print(f"  ✓ era '{data['era']}' in schema enum")
        elif "characterId" in data:
            # 人物卡
            print(f"== {name} ==")
            print(f"  characterId: {data['characterId']}")
            print(f"  role: {data.get('role', '?')}")
            print(f"  has visual_anchors: {'visual_anchors' in data}")
            print(f"  has initial_state_1985: {'initial_state_1985' in data}")
            print(f"  has state_2008: {'state_2008' in data}")
            print(f"  has case_01_parallel: {'case_01_parallel' in data}")
            print(f"  has initial_beliefs: {'initial_beliefs' in data}")
            print(f"  has behavioral_patterns: {'behavioral_patterns' in data}")
        elif "anchors" in data and "case_id" in data:
            # 锚点文件
            print(f"== {name} ==")
            print(f"  case_id: {data['case_id']}")
            print(f"  anchors: {len(data['anchors'])}")
            for a in data["anchors"]:
                print(f"    - {a['anchor_id']}: era={a['era']} label={a.get('label','-')}")
            print(f"  macro_endpoints: {len(data.get('macro_endpoints', []))}")
            print(f"  prop_objects: {len(data.get('prop_objects', []))}")
            print(f"  sound_motifs: {len(data.get('sound_motifs', []))}")
            print(f"  case_eras: {data.get('case_eras', [])}")
        else:
            print(f"== {name} ==")
            print(f"  UNKNOWN top-level keys: {list(data.keys())[:10]}")
    except Exception as e:
        print(f"== {name} ==")
        print(f"  ERROR: {e}")
    print()
