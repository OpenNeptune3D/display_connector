from src.elegoo_display import ElegooDisplayMapper


def test_initializing():
    mapper = ElegooDisplayMapper()
    assert mapper.page_mapping is not None
    assert mapper.data_mapping is not None

def test_default_light_config():
    mapper = ElegooDisplayMapper()
    lights = mapper.configure_default_lights()
    assert len(lights) == 0


def test_custom_filament_sensor_name():
    mapper = ElegooDisplayMapper()
    mapper.set_filament_sensor_name("filament_sensor")
    assert mapper.data_mapping["filament_switch_sensor filament_sensor"] is not None
    mapper.set_filament_sensor_name("custom")
    assert mapper.data_mapping["filament_switch_sensor custom"] is not None
    assert "filament_switch_sensor filament_sensor" not in mapper.data_mapping