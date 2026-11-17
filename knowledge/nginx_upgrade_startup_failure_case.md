# 案例：nginx 升级后启动失败（模块与依赖不匹配）

> 来源类型：自写整理（self_written，案例为教学用构造场景，不对应任何真实生产事故）
> 来源说明：依据 nginx 动态模块加载机制与 rpm 升级行为整理
> 适用版本：nginx 1.26.x + openEuler 24.03（示例）
> 来源链接：https://nginx.org/en/docs/
> 适用系统：linux_generic
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## 现象
升级主包后服务无法启动，journal 中出现两类报错：
- `dlopen() ... failed (libGeoIP.so.1: cannot open shared object file)`
- `module ... is not binary compatible`

## 成因链
1. 旧模块子包（如 `nginx-mod-http-geoip`）未随主包升级，模块 `.so` 仍在模块目录。
2. 该 `.so` 依赖的 `libGeoIP.so.1` 随 geoip 相关包被移除，动态链接失败。
3. 即便库存在，旧模块与新版 nginx 的 ABI 也不匹配，仍会报 `not binary compatible`。

## 处置思路
- 确认 `nginx -V` 的编译参数与 `load_module` 配置项指向的模块是否必需。
- 仓库有匹配版本则升级子包；无匹配版本则移除旧模块文件并清理配置中的 `load_module`。
- 修改后先用 `nginx -t` 校验配置，再启动服务并观察日志。

## 证据要求
结论必须基于实际日志与 `rpm -q` 输出；缺日志时只能给出待验证假设。

## 安全注意事项

- 案例为教学用构造场景，不对应真实事故；生产修复前先备份配置与包版本。

## 预期输出与判读

- `dlopen` 与 `not binary compatible` 同时出现时，优先怀疑模块与主包 ABI 不匹配，而不是配置语法。

## 常见错误

- 只改配置不查模块：`dlopen` 失败与配置无关。
- 强装不匹配的模块包：ABI 不兼容会持续失败。
- 忽略子包版本锁定：主包升级后旧子包依赖不满足。

## 排查思路

- journal 中的 `dlopen`/`not binary compatible` 是模块层证据。
- 对照 `rpm -q` 的主包与模块包 NEVRA，必要时回退或同步升级子包。
