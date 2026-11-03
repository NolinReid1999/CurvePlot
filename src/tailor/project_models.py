from pydantic import BaseModel, ConfigDict, Field


class Sheet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    id: int
    default_sheet: bool = False
    data: dict[str, list]
    new_col_num: int
    col_names: dict[str, str]
    calculated_column_expression: dict[str, str]
    column_metadata: dict[str, dict[str, str]] = Field(default_factory=dict)
    excluded: dict[str, list[int]] = Field(default_factory=dict)


class Parameter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    value: float
    min: float
    max: float
    vary: bool


class Plot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    id: int
    data_sheet_id: int

    x_col: str
    y_col: str
    x_err_col: str | None
    y_err_col: str | None

    x_label: str
    y_label: str

    x_min: float | None
    x_max: float | None
    y_min: float | None
    y_max: float | None

    modelexpression: str
    parameters: list[Parameter]
    fit_domain: tuple[float, float] | None
    use_fit_domain: bool
    best_fit: bool

    show_initial_fit: bool
    draw_curve_option: int
    curve_style: dict[
        str, str | float | bool | dict[str, dict[str, str | float | bool]]
    ] = Field(default_factory=dict)
    fit_preset_key: str | None = None
    legend_label: str = ""
    legend_visible: bool = True
    fit_records: list[dict] = Field(default_factory=list)
    active_fit_id: int | None = None
    graph_settings: dict = Field(default_factory=dict)
    annotations: list[dict] = Field(default_factory=list)


class MultiPlotInfo(BaseModel):
    plot_id: int
    label: str
    color: str
    axis: str = "left"
    x_axis: str = "bottom"
    visible: bool = True
    style: dict = Field(default_factory=dict)
    errors: dict = Field(default_factory=dict)


class MultiPlot(BaseModel):
    name: str
    id: int
    x_label: str
    y_label: str

    x_min: float | None
    x_max: float | None
    y_min: float | None
    y_max: float | None

    plots: list[MultiPlotInfo]
    graph_settings: dict = Field(default_factory=dict)
    annotations: list[dict] = Field(default_factory=list)
    curve_style: dict = Field(default_factory=dict)


class Project(BaseModel):
    project_name: str | None = None
    schema_version: int = 10
    view_state: dict = Field(default_factory=dict)
    model_config = ConfigDict(extra="ignore")

    application: str
    version: str
    sheet_num: int
    plot_num: int
    sheets: list[Sheet]
    plots: list[Plot]
    multiplots: list[MultiPlot]
    tab_order: list[str]
    current_tab: int
