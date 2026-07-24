// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** List Data Sources GET /api/v1/data-sources */
export async function dataSourcesList(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.dataSourcesListParams,
  options?: { [key: string]: any }
) {
  return request<API.DataSourcePageView>("/api/v1/data-sources", {
    method: "GET",
    params: {
      // page has a default value: 1
      page: "1",
      // pageSize has a default value: 20
      pageSize: "20",
      // sort has a default value: -created_at
      sort: "-created_at",
      ...params,
    },
    ...(options || {}),
  });
}

/** Get Data Source GET /api/v1/data-sources/${param0} */
export async function dataSourcesGet(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.dataSourcesGetParams,
  options?: { [key: string]: any }
) {
  const { dataSourceId: param0, ...queryParams } = params;
  return request<API.DataSourceDetail>(`/api/v1/data-sources/${param0}`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** Delete Data Source DELETE /api/v1/data-sources/${param0} */
export async function dataSourcesDelete(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.dataSourcesDeleteParams,
  options?: { [key: string]: any }
) {
  const { dataSourceId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/data-sources/${param0}`, {
    method: "DELETE",
    params: {
      ...queryParams,
    },
    ...(options || {}),
  });
}

/** Update Data Source PATCH /api/v1/data-sources/${param0} */
export async function dataSourcesUpdate(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.dataSourcesUpdateParams,
  body: API.UpdateDataSourceRequest,
  options?: { [key: string]: any }
) {
  const { dataSourceId: param0, ...queryParams } = params;
  return request<API.DataSourceDetail>(`/api/v1/data-sources/${param0}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** Download Original Source GET /api/v1/data-sources/${param0}/original */
export async function dataSourcesOriginal(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.dataSourcesOriginalParams,
  options?: { [key: string]: any }
) {
  const { dataSourceId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/data-sources/${param0}/original`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** Parse Data Source POST /api/v1/data-sources/${param0}/parse */
export async function dataSourcesParse(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.dataSourcesParseParams,
  body: API.ParseSourceRequest,
  options?: { [key: string]: any }
) {
  const { dataSourceId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/data-sources/${param0}/parse`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** Get Data Source References GET /api/v1/data-sources/${param0}/references */
export async function dataSourcesReferences(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.dataSourcesReferencesParams,
  options?: { [key: string]: any }
) {
  const { dataSourceId: param0, ...queryParams } = params;
  return request<API.DataSourceReferenceView[]>(
    `/api/v1/data-sources/${param0}/references`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Upload Data Sources POST /api/v1/data-sources/uploads */
export async function dataSourcesUpload(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.dataSourcesUploadParams,
  body: API.BodyDataSourcesUpload,
  options?: { [key: string]: any }
) {
  const formData = new FormData();

  Object.keys(body).forEach((ele) => {
    const item = (body as any)[ele];

    if (item !== undefined && item !== null) {
      if (typeof item === "object" && !(item instanceof File)) {
        if (item instanceof Array) {
          item.forEach((f) => formData.append(ele, f || ""));
        } else {
          formData.append(
            ele,
            new Blob([JSON.stringify(item)], { type: "application/json" })
          );
        }
      } else {
        formData.append(ele, item);
      }
    }
  });

  return request<API.UploadBatchResult>("/api/v1/data-sources/uploads", {
    method: "POST",
    params: { ...params },
    data: formData,
    requestType: "form",
    ...(options || {}),
  });
}
