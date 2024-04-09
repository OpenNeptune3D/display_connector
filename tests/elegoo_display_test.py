from src.elegoo_display import ElegooDisplayMapper

def test_initializing():
    mapper = ElegooDisplayMapper()
    assert mapper.page_mapping is not None
    assert mapper.data_mapping is not None
