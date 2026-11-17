# RPM 依赖冲突与升级失败判读

> 来源类型：自写整理（self_written）
> 来源说明：依据 rpm/dnf 依赖求解行为与常见错误文本整理
> 适用版本：dnf 4.x（openEuler 24.03 / 麒麟 V10 常见）
> 来源链接：https://dnf.readthedocs.io/
> 适用系统：linux_generic
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## 典型报错与含义
- `nothing provides <cap> needed by <pkg>`：仓库内没有能满足该能力的包，通常是版本未同步或仓库不含该子包。
- `package <a> conflicts with <b>`：两个包声明了互斥文件或显式 Conflicts。
- `requires <pkg> = <version>`：精确版本锁定，主包升级后旧子包会变成"依赖不满足"。

## 处理顺序
1. 用 `dnf repoquery --requires <pkg>` 确认依赖是否在仓库内可见。
2. 用 `dnf list --showduplicates <pkg>` 确认可用版本，判断是否存在匹配子包。
3. 若仓库确实缺失匹配版本，优先移除或禁用旧模块，而不是强装不匹配版本。
4. `--nodeps` 会跳过依赖检查，可能留下运行期加载失败，不建议作为常规手段。

## 与运行期的关系
依赖满足只代表安装期可解；运行期仍可能因为库文件缺失、ABI 不匹配而在启动时失败。

## 安全注意事项

- 不要用 `--nodeps --force` 绕过依赖；这会把安装期问题推迟成运行期加载失败。

## 预期输出与判读

- 依赖满足只代表安装期可解，启动仍可能因 `dlopen` 失败；必须结合 journal 验证。

## 常见错误

- 直接 `--nodeps` 装上：安装成功但运行期 `dlopen` 失败。
- 只升级主包不升级子包：精确版本依赖导致 `requires` 不满足。
- 把仓库缺包当成包损坏：先 `repoquery` 确认仓库可见性。

## 排查思路

- 安装期依赖 → 运行期加载 → 服务状态，逐层验证。
- 依赖结论要附 `rpm -q --requires` 与 journal 证据。
