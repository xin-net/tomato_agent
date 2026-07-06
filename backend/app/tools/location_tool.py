from pydantic import BaseModel


class LocationObservation(BaseModel):
    location: str
    location_source: str
    latitude: float | None = None
    longitude: float | None = None
    location_error: str | None = None
    requires_confirmation: bool = True
    note: str


class LocationTool:
    name = "LocationTool"
    description = "解析本轮病例应该使用的种植地点，处理用户显式地点、病例记忆和浏览器定位的优先级。"

    def observe(
        self,
        fallback_location: str,
        browser_latitude: float | None = None,
        browser_longitude: float | None = None,
        browser_location_label: str | None = None,
        browser_location_source: str | None = None,
        browser_location_error: str | None = None,
        explicit_location: str | None = None,
        previous_location: str | None = None,
        previous_location_source: str | None = None,
    ) -> LocationObservation:
        if explicit_location:
            return LocationObservation(
                location=explicit_location,
                location_source="user_explicit",
                requires_confirmation=False,
                note="用户本轮明确提供了种植地点，覆盖浏览器当前位置。",
            )

        if previous_location and previous_location_source == "user_explicit":
            return LocationObservation(
                location=previous_location,
                location_source="case_memory_user_location",
                requires_confirmation=True,
                note="沿用该病例之前由用户明确提供的种植地点。",
            )

        if browser_latitude is not None and browser_longitude is not None:
            return LocationObservation(
                location=browser_location_label or "浏览器定位",
                location_source=browser_location_source or "browser",
                latitude=browser_latitude,
                longitude=browser_longitude,
                requires_confirmation=True,
                note="使用浏览器授权返回的当前位置；如果植株不在当前位置，需要用户纠正。",
            )

        return LocationObservation(
            location=fallback_location,
            location_source=browser_location_source or "manual",
            location_error=browser_location_error,
            requires_confirmation=True,
            note="没有可用坐标，只能按用户文字和病例环境线索判断。",
        )
