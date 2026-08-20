import json

import numpy as np

from annotate_ground_truth import save_annotation
from annotate_ocr import _state, load_pipeline_drafts, save_ocr_annotation
from annotate_orientation import save_orientation
from detector import write_image
from recognition_contract import CONTACT_FIELDS


def _fixture(tmp_path):
    input_dir=tmp_path/"picture";input_dir.mkdir();source=input_dir/"sample.png";write_image(source,np.full((500,800,3),255,np.uint8));extraction=tmp_path/"ground_truth.json";saved=save_annotation(extraction,input_dir,source.name,[[[100,100],[700,100],[700,450],[100,450]]]);return input_dir,extraction,saved["cards"][0]["ground_truth_card_id"]


def test_orientation_ground_truth_allows_unknown(tmp_path):
    input_dir,extraction,card_id=_fixture(tmp_path);target=tmp_path/"orientation.json"
    saved=save_orientation(target,input_dir,extraction,card_id,"unknown")
    assert saved["correction_rotation"]=="unknown"
    saved=save_orientation(target,input_dir,extraction,card_id,270)
    assert saved["correction_rotation"]==270


def test_ocr_ground_truth_accepts_absent_email(tmp_path):
    input_dir,extraction,card_id=_fixture(tmp_path);orientation=tmp_path/"orientation.json";save_orientation(orientation,input_dir,extraction,card_id,0);contact={name:{"state":"absent","value":None} for name in CONTACT_FIELDS}
    saved=save_ocr_annotation(tmp_path/"ocr.json",input_dir,extraction,orientation,card_id,[{"text":"株式会社青柳","source":"printed","legibility":"readable"}],contact)
    assert saved["lines"][0]["ground_truth_line_id"]=="gt-line-001"
    assert saved["contact"]["email"]=={"state":"absent","value":None}


def test_ai_draft_prefills_form_but_is_not_ground_truth(tmp_path):
    input_dir,extraction,card_id=_fixture(tmp_path);orientation=tmp_path/"orientation.json";save_orientation(orientation,input_dir,extraction,card_id,0)
    ground_truth=json.loads(extraction.read_text(encoding="utf-8"));corners=ground_truth["images"]["sample.png"]["cards"][0]["corners"]
    output=tmp_path/"output";directory=output/"sample";directory.mkdir(parents=True)
    (directory/"result.json").write_text(json.dumps({"cards":[{"filename":"card01.png","corners":corners}]}),encoding="utf-8")
    (directory/"card01.ocr.ykr.json").write_text(json.dumps({"status":"succeeded","lines":[{"text":"株式会社青柳","source":"printed","legibility":"readable"}]}),encoding="utf-8")
    fields={name:{"state":"absent","display_value":None,"candidate_value":None} for name in CONTACT_FIELDS};fields["company_name"]={"state":"present","display_value":"株式会社青柳","candidate_value":None}
    (directory/"card01.contact.ykr.json").write_text(json.dumps({"status":"succeeded","fields":fields}),encoding="utf-8")
    drafts=load_pipeline_drafts(extraction,output);state=_state(input_dir,extraction,orientation,tmp_path/"ocr.json",drafts);card=state["cards"][0]
    assert card["draft"] is True
    assert card["annotated"] is False
    assert card["lines"][0]["text"]=="株式会社青柳"
    assert card["contact"]["company_name"]=={"state":"present","value":"株式会社青柳"}
