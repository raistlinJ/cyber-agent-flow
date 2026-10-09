import hashlib
import json
from pathlib import Path
from session_logger import SessionLogger


def test_evidence_links_full_output_and_survives_continuation(tmp_path):
    events=[];logger=SessionLogger('trial-1',{},str(tmp_path),event_callback=events.append)
    text='observed service configuration\n'*300
    first=logger.log_tool_call('curl',{'url':'http://lab'},text)
    root=Path(logger.run_dir);record=json.loads((root/'tool_calls'/first).read_text())
    assert record['evidence_id']=='trial-1:tool-000001'
    assert record['output_sha256']==hashlib.sha256(text.encode()).hexdigest()
    assert (root/record['output_file']).read_text()==text
    assert events[0]['evidence_id']==record['evidence_id']
    resumed=SessionLogger('trial-1',{},str(tmp_path))
    second=resumed.log_tool_call('curl',{},'new result')
    assert second!=first
    assert json.loads((root/'tool_calls'/second).read_text())['evidence_id']=='trial-1:tool-000002'
    assert json.loads((root/'tool_calls'/first).read_text())==record
