"""W10 smoke test — verify all 6 deliverables work end-to-end."""
import sys
sys.path.insert(0, r'D:/G1-ai-native')
sys.path.insert(0, r'D:/G1-ai-native/server')
sys.path.insert(0, r'D:/G1-ai-native/tools')

# Force UTF-8
import io
for stream_name in ('stdout', 'stderr'):
    stream = getattr(sys, stream_name, None)
    if stream is None:
        continue
    if hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(encoding='utf-8')
            continue
        except (ValueError, OSError):
            pass
    if hasattr(stream, 'buffer'):
        try:
            setattr(sys, stream_name, io.TextIOWrapper(stream.buffer, encoding='utf-8'))
        except (ValueError, OSError):
            pass

print('===== W10 SMOKE TEST =====')

# 1. Analytics warehouse
print('\n[1/6] server/analytics_warehouse.py')
from server.analytics_warehouse import (
    WeeklyReportBuilder, build_analytics_router,
    _humanize_window, _parse_window,
)
report = WeeklyReportBuilder().build()
assert report.window == '7d'
assert 'kpis' in report.payload
assert 'recallFunnel' in report.payload
assert 'sceneCompletion' in report.payload
assert 'mandatoryEcho' in report.payload
assert 'paymentFunnel' in report.payload
assert 'retentionCurve' in report.payload
assert 'redLineLimits' in report.payload
print('  PASS  weekly report built; markdown lines:', len(report.markdown.split('\n')))

# 2. Content update pipeline
print('\n[2/6] tools/content_update_pipeline.py')
from tools.content_update_pipeline import (
    BlueGreenDeployer, ContentUpdatePipeline, StepStatus, _git_root,
)
deployer = BlueGreenDeployer.from_repo(_git_root())
assert deployer.current() in ('blue', 'green')
print('  PASS  blue/green pointer:', deployer.current())
pipeline = ContentUpdatePipeline()
run = pipeline.publish(files=[], message='smoke test', version='v0.0.0-smoke', dry_run=True)
print('  PASS  dry-run publish status:', run.status.value)

# 3. A/B testing
print('\n[3/6] server/ab_testing.py')
from server.ab_testing import (
    ABTestingService, ThompsonBandit, BanditPolicy, ArmStats,
    seed_builtin_experiments, BUILTIN_EXPERIMENTS,
)
assert len(BUILTIN_EXPERIMENTS) == 3
service = ABTestingService()
seed_builtin_experiments(service)
exp_ids = list(service.repo.list_experiments())
assert len(exp_ids) == 3
print('  PASS  3 built-in experiments seeded:', [e['experimentId'] for e in exp_ids])

# 4. Feedback
print('\n[4/6] server/feedback.py')
import server.feedback  # noqa
from db import init_db
init_db()
from server.feedback import FeedbackService, FeedbackCategory
svc = FeedbackService()
rec = svc.submit_feedback(body='游戏不错', rating=5, user_id='smoke')
assert 'feedbackId' in rec
assert rec['isP0'] is False
print('  PASS  feedback submitted; categories:', rec['categories'])
rec_p0 = svc.submit_feedback(body='卡死 退钱', rating=1, user_id='smoke')
assert rec_p0['isP0'] is True
print('  PASS  P0 detected:', rec_p0['p0TrackerId'][:8])

# 5. Content workshop
print('\n[5/6] tools/content_workshop.py')
from tools.content_workshop import validate_file, upload_file, CheckVerdict
from pathlib import Path
target = Path(r'D:/G1-ai-native/content/case_01_revolution_street/scenes/photo_lab_2008.yaml')
report = validate_file(target)
assert report.document_kind == 'scene_contract'
print('  PASS  scene contract validated:', report.overall.value)

# 6. Operations dashboard
print('\n[6/6] infra/dashboards/operations.json')
import json
with open(r'D:/G1-ai-native/infra/dashboards/operations.json', encoding='utf-8') as f:
    d = json.load(f)
assert d['title']
assert d['uid'] == 'g1n-operations'
assert len(d['panels']) >= 12
print('  PASS  dashboard has', len(d['panels']), 'panels, uid:', d['uid'])

print('\n===== ALL 6 DELIVERABLES OK =====')
