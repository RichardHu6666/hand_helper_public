# sign_cloud_v1

`sign_cloud_v1` 鏄€滄墜璇€氣€濅簯绔熀鍏冨尮閰嶆湇鍔°€傚綋鍓嶇増鏈?`0.2.0-stream` 鍦ㄤ繚鐣欐棫鐨勫崟甯?鍒嗘鍖归厤鎺ュ彛鍩虹涓婏紝鏂板绔晶閫愬抚涓婁紶 primitive stream銆佷簯绔寜 session rolling buffer 鍋?lite SQLite 璇嶈〃杩炵画鍔ㄤ綔鍖归厤銆?

褰撳墠鐗堟湰淇濈暀 primitive stream 涓婚摼璺紝骞舵帴鍏ュ€欓€夊唴 RAG rerank銆佸彞瀛愮骇 fallback/鍙€?LLM 杈撳嚭锛涗笉涓婁紶鍥剧墖銆佽棰戙€侀煶棰戠粰浜戠妯″瀷锛屼笉鍋?EPUB 瑙ｆ瀽锛屼笉鍋氱敤鎴烽壌鏉冿紝涓嶅寘鍚?ESP32 绔?HTTP 涓婁紶浠ｇ爜銆?

## 鐩綍缁撴瀯

```text
/root/sign_cloud_v1
鈹溾攢鈹€ app
鈹?  鈹溾攢鈹€ main.py
鈹?  鈹溾攢鈹€ schemas.py
鈹?  鈹溾攢鈹€ storage.py
鈹?  鈹溾攢鈹€ primitive_text_parser.py
鈹?  鈹溾攢鈹€ stream_models.py
鈹?  鈹溾攢鈹€ smoothing.py
鈹?  鈹溾攢鈹€ rolling_buffer.py
鈹?  鈹溾攢鈹€ span_generator.py
鈹?  鈹溾攢鈹€ span_summary.py
鈹?  鈹溾攢鈹€ wide_filter.py
鈹?  鈹溾攢鈹€ frame_step_scorer.py
鈹?  鈹溾攢鈹€ step_aligner.py
鈹?  鈹溾攢鈹€ candidate_scorer.py
鈹?  鈹溾攢鈹€ output_state_machine.py
鈹?  鈹溾攢鈹€ stream_decoder.py
鈹?  鈹溾攢鈹€ debug_builder.py
鈹?  鈹溾攢鈹€ matcher.py
鈹?  鈹斺攢鈹€ seed_data.py
鈹溾攢鈹€ data
鈹?  鈹溾攢鈹€ hand_language_vocabulary_lite.sqlite3
鈹?  鈹溾攢鈹€ vocab_seed.json
鈹?  鈹斺攢鈹€ hand_words.sqlite3
鈹溾攢鈹€ scripts
鈹?  鈹溾攢鈹€ init_db.py
鈹?  鈹溾攢鈹€ inspect_vocab.py
鈹?  鈹溾攢鈹€ debug_match.py
鈹?  鈹溾攢鈹€ debug_stream.py
鈹?  鈹斺攢鈹€ run_server.sh
鈹溾攢鈹€ tests
鈹溾攢鈹€ requirements.txt
鈹斺攢鈹€ README.md
```

## 瀹夎

```bash
cd /root/sign_cloud_v1
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 璇嶈〃

杩炵画娴佸尮閰嶅彧璇诲彇 lite 璇嶈〃锛?

```text
/root/sign_cloud_v1/data/hand_language_vocabulary_lite.sqlite3
```

琛ㄥ悕鍥哄畾涓猴細

```text
hand_language_vocabulary
```

瀛楁鍥哄畾涓猴細

```text
id, word_base, action_description, retrieval_text, primitive_text
```

妫€鏌ヨ瘝琛細

```bash
cd /root/sign_cloud_v1
source .venv/bin/activate
python scripts/inspect_vocab.py
```

閲嶅 timestamp 绛栫暐锛氬悓涓€ session 鍐呯浉鍚?`timestamp` 鐨勬柊甯т細瑕嗙洊鏃у抚锛涗笉鍚?timestamp 鍗充娇鍊掑簭鍒拌揪涔熶細鎸?`(timestamp_ms, seq_in_second)` 閲嶆柊鎺掑簭銆俙YYMMDD-HHMMSS-XXX` 涓殑 `XXX` 鍦?v1 涓寜鍚岀鍐呭抚搴忓彿鏄犲皠涓?100ms 闂撮殧锛岀敤浜庣獥鍙ｆ椂闀夸及璁°€?

## 鍚姩

```bash
cd /root/sign_cloud_v1
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 6666
```

涔熷彲浠ヨ繍琛岋細

```bash
bash scripts/run_server.sh
```

## 鍋ュ悍妫€鏌?

```bash
curl -s http://127.0.0.1:6666/health | python -m json.tool
```

蹇呴』鐪嬪埌 `ok=true`銆乣vocab.rows=109`銆乣vocab.loaded=true`銆俙embedding.backend=hash_fallback` 琛ㄧず褰撳墠鍙槸宸ョ▼閾捐矾楠岃瘉锛屼笉鏄湡瀹?BGE 璇箟妫€绱€?

鍏綉璋冭瘯锛?

```bash
curl -s <YOUR_SERVER_URL>/health | python -m json.tool
```

## Stream 璋冭瘯

鏈湴鑴氭湰浣跨敤 FastAPI TestClient 鐩存帴鏋勯€?primitive frames锛屼笉瑕佹眰鍏堝惎鍔ㄦ湇鍔★細

```bash
python scripts/debug_stream.py --preset left_right_single --debug
python scripts/debug_stream.py --preset dual_repeat --debug
python scripts/debug_stream.py --preset noisy_shape --debug
python scripts/debug_stream.py --jsonl tests/fixtures/stream_left_right.jsonl --debug
```

鏈熸湜鑳界湅鍒?`collecting -> pending -> confirmed`锛宑onfirmed 璇嶆潵鑷?lite SQLite 鐨勭湡瀹?`word_base`銆?

鍗曞抚 curl 绀轰緥锛?

```bash
curl -s -X POST http://127.0.0.1:6666/api/v1/stream/frame \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "dev-001",
    "timestamp": "260701-143012-001",
    "primitive": {
      "hand_count": 1,
      "dominant_side": "signer_right",
      "location": "signer_center_upper",
      "movement": "left_right",
      "bimanual_relation": "single_hand",
      "dominant_shape": "five",
      "nondominant_shape": "no_hand"
    },
    "debug": true
  }' | python -m json.tool
```

鏌ヨ session debug锛?

```bash
curl -s http://127.0.0.1:6666/api/v1/debug/session/dev-001 | python -m json.tool
```

娓呯┖ session锛?

```bash
curl -s -X POST http://127.0.0.1:6666/api/v1/debug/reset/dev-001 | python -m json.tool
```


## 鍥哄畾娴佹祴璇?

鍏堝惎鍔ㄦ湇鍔★細

```bash
bash scripts/run_server.sh
```

妫€鏌ュ仴搴风姸鎬佸拰 lite 璇嶈〃锛?

```bash
curl -s http://127.0.0.1:6666/health | python -m json.tool
```

鏈湴杩涚▼鍐呭浐瀹氭祦娴嬭瘯锛屼笉闇€瑕?HTTP 鏈嶅姟锛?

```bash
python scripts/debug_stream.py --jsonl tests/fixtures/stream_left_right_single.jsonl --debug
python scripts/debug_stream.py --jsonl tests/fixtures/stream_up_down_single.jsonl --debug
python scripts/debug_stream.py --jsonl tests/fixtures/stream_toward_away_single.jsonl --debug
python scripts/debug_stream.py --jsonl tests/fixtures/stream_dual_hand.jsonl --debug
python scripts/debug_stream.py --jsonl tests/fixtures/stream_noisy_shape.jsonl --debug
python scripts/debug_stream.py --jsonl tests/fixtures/stream_repeat_same_word.jsonl --debug
```

鏈満 HTTP 杩炵画鍙戝抚锛?

```bash
python scripts/http_stream_fixture.py --jsonl tests/fixtures/stream_left_right_single.jsonl --debug
```

鍏綉 HTTP 杩炵画鍙戝抚锛?

```bash
python scripts/http_stream_fixture.py \
  --url <YOUR_SERVER_URL> \
  --jsonl tests/fixtures/stream_left_right_single.jsonl \
  --debug
```

瑙傚療閲嶇偣锛?

- 鏄惁鍑虹幇 `collecting -> pending -> confirmed`銆?
- confirmed 鍦ㄧ鍑犲抚鍑虹幇銆?
- confirmed word 鏄惁鏉ヨ嚜 lite SQLite 鐨勭湡瀹?`word_base`銆?
- 鍚屼竴璇嶆槸鍚﹂噸澶?confirmed锛泂ummary 涓?`repeated_confirmed_suppressed=true` 琛ㄧず鏈噸澶嶈緭鍑哄悓涓€璇嶃€?
- `debug=true` 鏃舵煡鐪?`top_candidates`銆乣score_breakdown`銆乣conflict_fields` 鏄惁绗﹀悎褰撳墠 primitive 搴忓垪銆?


## Fixture 瀹¤鎶ュ憡

鐢熸垚褰撳墠鍥哄畾 JSONL fixture 鐨勫€欓€夈€佸垎鏁版媶瑙ｃ€佸啿绐佸瓧娈靛拰鍐崇瓥鍘熷洜鎶ュ憡锛?

```bash
python scripts/audit_fixture_results.py --debug
python scripts/audit_fixture_results.py --fixture tests/fixtures/stream_left_right_single.jsonl --top-k 5
```

榛樿杈撳嚭锛?

```text
reports/fixture_audit.md
reports/fixture_audit.json
```

鐢ㄩ€旓細

- 姣旇緝鍚?fixture 鐨?top candidates銆?
- 鍒ゆ柇 confirmed/pending 鐨勫師鍥犮€?
- 瑙傚療褰撳墠杈撳叆鏄惁琚煇涓瘝鏉″惛璧般€?
- 鍚庣画璋冨弬鍓嶅悗瀵规瘮鍒嗘暟銆佸啿绐佸瓧娈靛拰鍐崇瓥鍙樺寲銆?


## 璇嶅簱鐩镐技鎬у璁?

妫€鏌?lite SQLite 涓?primitive_text 鐨勯噸澶嶆ā鏉裤€佸鏉剧鍚嶉噸澶嶅拰楂樺惛闄勬ā鏉匡細

```bash
python scripts/audit_vocab_primitive_similarity.py
python scripts/audit_fixture_results.py --debug
```

杈撳嚭锛?

```text
reports/vocab_primitive_similarity.md
reports/vocab_primitive_similarity.json
reports/fixture_problem_analysis.md
```

鐢ㄩ€旓細

- 鏌ョ湅 primitive_text 瀹屽叏閲嶅缁勩€?
- 鏌ョ湅 `hand_count + movement + location + bimanual_relation` 鐨?step signature 閲嶅缁勩€?
- 鏌ョ湅蹇界暐 location/shape 鍚庣殑 loose signature 閲嶅缁勩€?
- 鍒嗘瀽鏌愪釜 fixture 鏄惁琚噸澶嶆ā鏉挎垨楂樺惛闄勬ā鏉垮惛璧般€?
- 璋冨弬鍓嶅悗瀵规瘮 `score_breakdown` 涓殑 `ambiguity_penalty`銆乣unknown_penalty`銆乣conflict_penalty`銆?


## RAG 閲嶆帓涓庡彞瀛愮骇杈撳嚭

鐢熸垚鎴栧埛鏂?embedding cache锛?

```bash
python scripts/build_embeddings.py --model BAAI/bge-small-zh-v1.5 --device cpu
```

褰撳墠鐜濡傛灉娌℃湁瀹夎 `sentence-transformers`锛岃剼鏈細浣跨敤纭畾鎬?hash fallback 鐢熸垚鏈湴 cache锛屼究浜庣绾块獙璇侊紱瀹夎鐪熷疄妯″瀷渚濊禆鍚庝細浼樺厛浣跨敤鐪熷疄妯″瀷銆?

璋冭瘯鍊欓€夊唴 RAG 閲嶆帓锛?

```bash
python scripts/debug_rag_rerank.py --fixture tests/fixtures/stream_left_right_single.jsonl --top-k 5
```

璋冭瘯鍙ュ瓙绾ц緭鍑猴紱娌℃湁 LLM key 鏃朵細 fallback 涓虹‘璁よ瘝鎷兼帴锛?

```bash
python scripts/debug_sentence_compose.py --words 鍘曟墍 姘?鍐嶈
python scripts/debug_sentence_compose.py --json tests/fixtures/sentence_candidates_simple.json
```

鏈嶅姟鐘舵€佷腑浼氭樉绀猴細

```bash
curl -s http://127.0.0.1:6666/health | python -m json.tool
```

閲嶇偣瀛楁锛?

- `embedding.enabled`
- `embedding.loaded`
- `embedding.rows`
- `embedding.backend`
- `embedding.embedding_dim`
- `llm.enabled`
- `llm.configured`

鏌ヨ鍜岄噸缃彞瀛愮姸鎬侊細

```bash
curl -s http://127.0.0.1:6666/api/v1/sentence/dev-001 | python -m json.tool
curl -s -X POST http://127.0.0.1:6666/api/v1/sentence/reset/dev-001 | python -m json.tool
```

## HTTP 闀挎祦鍘嬫祴

楠岃瘉鍗?session 闀挎祦銆佸弻 session 浜ら敊銆乺eset 鍚庨噸鍙戝拰闈?debug 楂橀鍝嶅簲锛?

```bash
python scripts/stress_stream_sessions.py
```

榛樿杈撳嚭锛?

```text
reports/http_stream_stress.md
```

瑙傚療閲嶇偣锛?

- 鏃?HTTP 500銆?
- 鍗?session 杩炵画鍚岃瘝涓嶉噸澶?confirmed銆?
- 鍙?session 鐘舵€佷笉涓层€?
- reset 鍚庡彲閲嶆柊 confirmed銆?
- `/api/v1/stream/frame` 闈?debug 鍝嶅簲浠嶅寘鍚ǔ瀹?`sentence` 瀵硅薄銆?

## 鏃ф帴鍙?

鏃ф帴鍙ｄ粛淇濈暀锛?

```bash
python scripts/debug_match.py --preset hello
python scripts/debug_match.py --preset up_down
python scripts/debug_match.py --preset dual
```

```bash
curl -s -X POST http://127.0.0.1:6666/api/v1/match/primitive \
  -H 'Content-Type: application/json' \
  -d '{"primitive":{"hand_count":1,"dominant_side":"signer_right","location":"signer_right_upper","movement":"left_right","bimanual_relation":"single_hand","dominant_shape":"no_gesture","nondominant_shape":"no_hand"},"top_k":5,"debug":true}' \
  | python -m json.tool
```

## 娴嬭瘯

```bash
cd /root/sign_cloud_v1
source .venv/bin/activate
pytest -q
```

褰撳墠娴嬭瘯瑕嗙洊 parser銆乴ite vocab load銆亀ide filter銆乻tep aligner銆乻tream decoder銆乻tream API銆佸搷搴斿绾︺€丷AG/sentence fallback銆侀噸澶嶈緭鍑烘姂鍒讹紝骞朵繚鐣欐棫 match 鎺ュ彛娴嬭瘯銆?

## 褰撳墠闄愬埗

- 杩炵画娴佸尮閰嶆柟娉曞浐瀹氫负 `primitive_stream_alignment_v1`銆?
- lite v3 璇嶈〃瑙勬ā涓?109 鏉★紱full 璇嶅簱涓嶄綔涓洪粯璁ょ敓浜ц瘝搴撱€?
- `/api/v1/stream/frame` 浣跨敤杩涚▼鍐呭唴瀛樼淮鎶?session buffer锛岄噸鍚悗 session 鐘舵€佹竻绌恒€?
- shape 鏉冮噸浣庝簬 movement/hand_count/location锛沗no_gesture`銆乣unknown` 涓嶄綔涓哄己鍐茬獊銆?
- 褰撳墠 embedding cache 浠嶅彲鑳芥槸 `hash_fallback`锛涘彧鏈?`embedding.backend=sentence_transformers` 鏃舵墠浠ｈ〃鐪熷疄 BGE銆?
- LLM 榛樿鍏抽棴锛涙棤 key 鎴栬皟鐢ㄥけ璐ユ椂浣跨敤 confirmed words 鎷兼帴 fallback銆?

