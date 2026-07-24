// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** Get Parsed Source Version GET /api/v1/parsed-source-versions/${param0} */
export async function parsedSourceVersionsGet(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsGetParams,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<API.ParsedSourceVersionDetailView>(
    `/api/v1/parsed-source-versions/${param0}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Delete Parsed Source Version DELETE /api/v1/parsed-source-versions/${param0} */
export async function parsedSourceVersionsDelete(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsDeleteParams,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<any>(`/api/v1/parsed-source-versions/${param0}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** List Parsed Artifacts GET /api/v1/parsed-source-versions/${param0}/artifacts */
export async function parsedSourceVersionsArtifacts(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsArtifactsParams,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<API.ParsedArtifactListView>(
    `/api/v1/parsed-source-versions/${param0}/artifacts`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** List Parsed Assets GET /api/v1/parsed-source-versions/${param0}/assets */
export async function parsedSourceVersionsAssets(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsAssetsParams,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<API.ParsedAssetPageView>(
    `/api/v1/parsed-source-versions/${param0}/assets`,
    {
      method: "GET",
      params: {
        // page has a default value: 1
        page: "1",
        // pageSize has a default value: 20
        pageSize: "20",
        ...queryParams,
      },
      ...(options || {}),
    }
  );
}

/** Download Parsed Asset GET /api/v1/parsed-source-versions/${param0}/assets/${param1} */
export async function parsedSourceVersionsAssetContent(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsAssetContentParams,
  options?: { [key: string]: any }
) {
  const {
    parsedSourceVersionId: param0,
    assetId: param1,
    ...queryParams
  } = params;
  return request<any>(
    `/api/v1/parsed-source-versions/${param0}/assets/${param1}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** List Parsed Blocks GET /api/v1/parsed-source-versions/${param0}/blocks */
export async function parsedSourceVersionsBlocks(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsBlocksParams,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<API.ParsedBlockPageView>(
    `/api/v1/parsed-source-versions/${param0}/blocks`,
    {
      method: "GET",
      params: {
        // page has a default value: 1
        page: "1",
        // pageSize has a default value: 20
        pageSize: "20",
        ...queryParams,
      },
      ...(options || {}),
    }
  );
}

/** Get Parsed Markdown GET /api/v1/parsed-source-versions/${param0}/markdown */
export async function parsedSourceVersionsMarkdown(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsMarkdownParams,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<API.ParsedMarkdownView>(
    `/api/v1/parsed-source-versions/${param0}/markdown`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Get Parsed Source References GET /api/v1/parsed-source-versions/${param0}/references */
export async function parsedSourceVersionsReferences(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsReferencesParams,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<API.DataSourceReferenceView[]>(
    `/api/v1/parsed-source-versions/${param0}/references`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Create Parsed Source Reparse POST /api/v1/parsed-source-versions/${param0}%3Acreate-reparse */
export async function parsedSourceVersionsCreateReparse(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsCreateReparseParams,
  body: API.CreateReparseRequest,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<API.ParseSourceResponse>(
    `/api/v1/parsed-source-versions/${param0}%3Acreate-reparse`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}

/** Resume Parsed Source Provider Query POST /api/v1/parsed-source-versions/${param0}%3Aresume-provider-query */
export async function parsedSourceVersionsResumeProviderQuery(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.parsedSourceVersionsResumeProviderQueryParams,
  options?: { [key: string]: any }
) {
  const { parsedSourceVersionId: param0, ...queryParams } = params;
  return request<any>(
    `/api/v1/parsed-source-versions/${param0}%3Aresume-provider-query`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}
