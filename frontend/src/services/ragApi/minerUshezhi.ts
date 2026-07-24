// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** Get Mineru Settings GET /api/v1/settings/mineru */
export async function mineruSettingsGet(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.mineruSettingsGetParams,
  options?: { [key: string]: any }
) {
  return request<API.MinerUSettingsView>("/api/v1/settings/mineru", {
    method: "GET",
    params: { ...params },
    ...(options || {}),
  });
}

/** Update Mineru Settings PATCH /api/v1/settings/mineru */
export async function mineruSettingsUpdate(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.mineruSettingsUpdateParams,
  body: API.UpdateMinerUSettingsRequest,
  options?: { [key: string]: any }
) {
  return request<API.MinerUSettingsView>("/api/v1/settings/mineru", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...params },
    data: body,
    ...(options || {}),
  });
}

/** Test Mineru Settings POST /api/v1/settings/mineru${test} */
export async function mineruSettingsTest(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.mineruSettingsTestParams,
  body: API.MinerUSettingsTestRequest,
  options?: { [key: string]: any }
) {
  return request<any>(`/api/v1/settings/mineru${test}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...params },
    data: body,
    ...(options || {}),
  });
}
