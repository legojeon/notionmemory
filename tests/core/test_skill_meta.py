from notionmemory.core.config import Config, SkillMeta


def test_skill_meta_reads_and_writes_own_section(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("skills: {}\n", encoding="utf-8")
    cfg = Config.load(str(p))
    meta = SkillMeta(cfg, "calendar")
    assert meta.get_meta("data_source_id") == ""
    meta.set_meta("data_source_id", "ds_cal")
    assert meta.get_meta("data_source_id") == "ds_cal"
    reloaded = Config.load(str(p))
    assert reloaded.skill_options("calendar")["data_source_id"] == "ds_cal"
    # 다른 스킬 섹션과 격리
    assert "data_source_id" not in reloaded.skill_options("memory")


def test_skill_meta_memory_only_config_no_path():
    cfg = Config({}, "")
    meta = SkillMeta(cfg, "calendar")
    meta.set_meta("k", "v")
    assert meta.get_meta("k") == "v"
