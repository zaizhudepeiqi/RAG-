declare namespace API {
  type AdminProfile = {
    /** Firstloginrequired */
    firstLoginRequired: boolean;
    /** Id */
    id: string;
    /** Username */
    username: string;
  };

  type authChangePasswordParams = {
    rag_csrf?: string | null;
    rag_admin_access?: string | null;
  };

  type authLogoutParams = {
    rag_csrf?: string | null;
    rag_admin_access?: string | null;
  };

  type authMeParams = {
    rag_admin_access?: string | null;
  };

  type capabilitiesGetVersionParams = {
    code: string;
    version: string;
    rag_admin_access?: string | null;
  };

  type capabilitiesListParams = {
    category?: string | null;
    includeDisabled?: boolean;
    rag_admin_access?: string | null;
  };

  type CapabilityOptionResponse = {
    /** Category */
    category?: string | null;
    /** Code */
    code: string;
    /** Configschema */
    configSchema?: Record<string, any> | null;
    /** Description */
    description: string;
    /** Enabled */
    enabled: boolean;
    /** Name */
    name: string;
    /** Preferredsourcefeatures */
    preferredSourceFeatures?: string[];
    /** Requiredsourcefeatures */
    requiredSourceFeatures?: string[];
    /** Uischema */
    uiSchema?: Record<string, any> | null;
    /** Unavailablereason */
    unavailableReason?: string | null;
    /** Version */
    version: string;
    /** Visible */
    visible: boolean;
  };

  type ChangePasswordRequest = {
    /** Confirmpassword */
    confirmPassword: string;
    /** Newpassword */
    newPassword: string;
    /** Oldpassword */
    oldPassword: string;
  };

  type CloudProcessingConsent = {
    /** Accepted */
    accepted: boolean;
    /** Termsversion */
    termsVersion: string;
  };

  type CreateModelProviderRequest = {
    /** Baseurl */
    baseUrl: string;
    /** Credential */
    credential: string;
    /** Displayname */
    displayName: string;
    /** Providertype */
    providerType: string;
    /** Supportedmodeltypes */
    supportedModelTypes?: ModelType[] | null;
  };

  type CreateModelRequest = {
    /** Contextwindow */
    contextWindow?: number | null;
    /** Defaultparams */
    defaultParams?: Record<string, any>;
    /** Displayname */
    displayName: string;
    /** Embeddingdimension */
    embeddingDimension?: number | null;
    /** Maxoutputtokens */
    maxOutputTokens?: number | null;
    /** Modelname */
    modelName: string;
    modelType: ModelType;
    /** Providerid */
    providerId: string;
  };

  type DependencyHealthItem = {
    /** Code */
    code:
      | "postgresql"
      | "redis"
      | "chroma"
      | "storage"
      | "celery"
      | "mineru"
      | "models";
    /** Message */
    message: string;
    /** Status */
    status: "healthy" | "degraded" | "unhealthy" | "not_configured";
  };

  type DependencyHealthResponse = {
    /** Dependencies */
    dependencies: DependencyHealthItem[];
    /** Status */
    status: "healthy" | "degraded" | "unhealthy";
    /** Timestamp */
    timestamp: string;
    /** Traceid */
    traceId: string;
    /** Version */
    version: string;
  };

  type DiscoveredModelView = {
    /** Alreadyconfiguredmodelids */
    alreadyConfiguredModelIds: string[];
    /** Discoverymetadata */
    discoveryMetadata: Record<string, any>;
    /** Providermodelname */
    providerModelName: string;
    /** Suggesteddisplayname */
    suggestedDisplayName: string;
    /** Supportedmodeltypes */
    supportedModelTypes: ModelType[];
  };

  type HealthResponse = {
    /** Status */
    status: "healthy" | "degraded" | "unhealthy";
    /** Timestamp */
    timestamp: string;
    /** Traceid */
    traceId: string;
    /** Version */
    version: string;
  };

  type HTTPValidationError = {
    /** Detail */
    detail?: ValidationError[];
  };

  type LastModelVerificationView = {
    /** Errorcode */
    errorCode?: string | null;
    /** Latencyms */
    latencyMs?: number | null;
    /** Status */
    status: string;
    /** Testedat */
    testedAt: string;
  };

  type LoginRequest = {
    /** Password */
    password: string;
    /** Username */
    username: string;
  };

  type LoginResponse = {
    admin: AdminProfile;
    /** Csrftoken */
    csrfToken: string;
    /** Firstloginrequired */
    firstLoginRequired: boolean;
  };

  type mineruSettingsGetParams = {
    rag_admin_access?: string | null;
  };

  type mineruSettingsUpdateParams = {
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type MinerUSettingsView = {
    /** Baseurl */
    baseUrl: string;
    /** Cloudprocessingconfirmedat */
    cloudProcessingConfirmedAt?: string | null;
    defaultParseConfig: ParseConfigDto;
    /** Polltimeoutseconds */
    pollTimeoutSeconds: number;
    /** Revision */
    revision: number;
    /** Termsversion */
    termsVersion?: string | null;
    /** Tokenconfigured */
    tokenConfigured: boolean;
    /** Tokenmasked */
    tokenMasked?: string | null;
  };

  type ModelPageView = {
    /** Items */
    items: ModelView[];
    /** Page */
    page: number;
    /** Pagesize */
    pageSize: number;
    /** Total */
    total: number;
  };

  type ModelProviderPageView = {
    /** Items */
    items: ModelProviderView[];
    /** Page */
    page: number;
    /** Pagesize */
    pageSize: number;
    /** Total */
    total: number;
  };

  type modelProvidersCreateParams = {
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelProvidersDeleteParams = {
    providerId: string;
    expectedRevision: number;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelProvidersDiscoveredModelsListParams = {
    providerId: string;
    modelType?: ModelType | null;
    status?: "available" | "unavailable" | "unknown" | null;
    rag_admin_access?: string | null;
  };

  type modelProvidersDiscoverParams = {
    providerId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelProvidersGetParams = {
    providerId: string;
    rag_admin_access?: string | null;
  };

  type modelProvidersListParams = {
    search?: string | null;
    enabled?: boolean | null;
    page?: number;
    pageSize?: ProviderPageSize;
    sort?: "display_name" | "-display_name" | "created_at" | "-created_at";
    rag_admin_access?: string | null;
  };

  type modelProvidersTestParams = {
    providerId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelProvidersUpdateParams = {
    providerId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type ModelProviderView = {
    /** Baseurl */
    baseUrl: string;
    /** Createdat */
    createdAt: string;
    /** Credentialconfigured */
    credentialConfigured: boolean;
    /** Credentialmasked */
    credentialMasked?: string | null;
    /** Displayname */
    displayName: string;
    /** Enabled */
    enabled: boolean;
    /** Id */
    id: string;
    /** Modelcount */
    modelCount: number;
    /** Providertype */
    providerType: string;
    /** Revision */
    revision: number;
    /** Updatedat */
    updatedAt: string;
  };

  type ModelReferenceView = {
    /** Displayname */
    displayName: string;
    /** Resourceid */
    resourceId: string;
    /** Resourcetype */
    resourceType: string;
    /** State */
    state: string;
  };

  type modelsCreateParams = {
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelsDeleteParams = {
    modelId: string;
    expectedRevision: number;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelsDisableParams = {
    modelId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelsEnableParams = {
    modelId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelsGetParams = {
    modelId: string;
    rag_admin_access?: string | null;
  };

  type modelsListParams = {
    providerId?: string | null;
    modelType?: ModelType | null;
    enabled?: boolean | null;
    verificationStatus?: "untested" | "passed" | "failed" | "stale" | null;
    search?: string | null;
    page?: number;
    pageSize?: ProviderPageSize;
    sort?: "display_name" | "-display_name" | "created_at" | "-created_at";
    rag_admin_access?: string | null;
  };

  type modelsReferencesParams = {
    modelId: string;
    rag_admin_access?: string | null;
  };

  type ModelStateRequest = {
    /** Expectedrevision */
    expectedRevision: number;
  };

  type modelsUpdateParams = {
    modelId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type modelsVerifyParams = {
    modelId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type ModelType = "llm" | "embedding" | "rerank" | "vision";

  type ModelView = {
    /** Capabilityversion */
    capabilityVersion: string;
    /** Configschema */
    configSchema: Record<string, any>;
    /** Contextwindow */
    contextWindow?: number | null;
    /** Defaultparams */
    defaultParams: Record<string, any>;
    /** Displayname */
    displayName: string;
    /** Embeddingdimension */
    embeddingDimension?: number | null;
    /** Enabled */
    enabled: boolean;
    /** Id */
    id: string;
    lastVerification?: LastModelVerificationView | null;
    /** Maxoutputtokens */
    maxOutputTokens?: number | null;
    /** Modelname */
    modelName: string;
    modelType: ModelType;
    provider: ResourceRef;
    /** Revision */
    revision: number;
    /** Usedbybotcount */
    usedByBotCount: number;
    /** Usedbyknowledgebasecount */
    usedByKnowledgeBaseCount: number;
    verificationStatus: VerificationStatus;
  };

  type OperationDetail = {
    /** Allowedactions */
    allowedActions: ("cancel" | "retry")[];
    /** Attempt */
    attempt: number;
    /** Errorcode */
    errorCode?: string | null;
    /** Errormessage */
    errorMessage?: string | null;
    /** Finishedat */
    finishedAt?: string | null;
    /** Heartbeatat */
    heartbeatAt?: string | null;
    /** Maxattempts */
    maxAttempts: number;
    /** Operationid */
    operationId: string;
    /** Progresscurrent */
    progressCurrent: number;
    /** Progresstotal */
    progressTotal?: number | null;
    /** Progressunit */
    progressUnit?: string | null;
    /** Queuedat */
    queuedAt: string;
    /** Resultsummary */
    resultSummary: Record<string, any>;
    /** Retryable */
    retryable: boolean;
    /** Stagecode */
    stageCode?: string | null;
    /** Stagelabel */
    stageLabel?: string | null;
    /** Startedat */
    startedAt?: string | null;
    status: OperationStatus;
    /** Statusurl */
    statusUrl: string;
    /** Targetid */
    targetId: string;
    /** Targettype */
    targetType: string;
    /** Tasktype */
    taskType: string;
    /** Warningcount */
    warningCount: number;
  };

  type OperationPage = {
    /** Items */
    items: OperationDetail[];
    /** Page */
    page: number;
    /** Pagesize */
    pageSize: number;
    /** Total */
    total: number;
  };

  type OperationPageSize = 20 | 50 | 100;

  type OperationRef = {
    /** Operationid */
    operationId: string;
    status: OperationStatus;
    /** Statusurl */
    statusUrl: string;
    /** Targetid */
    targetId: string;
    /** Targettype */
    targetType: string;
  };

  type operationsCancelParams = {
    operationId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type operationsGetParams = {
    operationId: string;
    rag_admin_access?: string | null;
  };

  type operationsListParams = {
    status?: string | null;
    taskType?: string | null;
    targetType?: string | null;
    targetId?: string | null;
    page?: number;
    pageSize?: OperationPageSize;
    sort?: "queued_at" | "-queued_at" | "created_at" | "-created_at";
    rag_admin_access?: string | null;
  };

  type operationsRetryParams = {
    operationId: string;
    rag_admin_access?: string | null;
    rag_csrf?: string | null;
  };

  type OperationStatus =
    | "queued"
    | "running"
    | "succeeded"
    | "partial_succeeded"
    | "failed"
    | "cancelled";

  type ParseConfigDto = {
    /** Extraformats */
    extraFormats?: string[];
    /** Forceproviderrefresh */
    forceProviderRefresh: boolean;
    /** Formulaenabled */
    formulaEnabled: boolean;
    /** Language */
    language: string;
    /** Modelversion */
    modelVersion: string;
    /** Ocrenabled */
    ocrEnabled: boolean;
    /** Pageranges */
    pageRanges?: string | null;
    /** Parsercode */
    parserCode: string;
    /** Tableenabled */
    tableEnabled: boolean;
  };

  type ProviderOperationRequest = {
    /** Expectedrevision */
    expectedRevision: number;
  };

  type ProviderPageSize = 20 | 50 | 100;

  type ResourceRef = {
    /** Displayname */
    displayName: string;
    /** Id */
    id: string;
  };

  type SuccessResponse = {
    /** Success */
    success?: boolean;
  };

  type UpdateMinerUSettingsRequest = {
    /** Baseurl */
    baseUrl: string;
    cloudProcessingConsent?: CloudProcessingConsent | null;
    defaultParseConfig: ParseConfigDto;
    /** Expectedrevision */
    expectedRevision: number;
    /** Polltimeoutseconds */
    pollTimeoutSeconds: number;
    /** Token */
    token?: string | null;
  };

  type UpdateModelProviderRequest = {
    /** Credential */
    credential?: string | null;
    /** Displayname */
    displayName?: string | null;
    /** Expectedrevision */
    expectedRevision: number;
  };

  type UpdateModelRequest = {
    /** Capabilityversion */
    capabilityVersion?: string | null;
    /** Configschema */
    configSchema?: Record<string, any> | null;
    /** Contextwindow */
    contextWindow?: number | null;
    /** Defaultparams */
    defaultParams?: Record<string, any> | null;
    /** Displayname */
    displayName?: string | null;
    /** Embeddingdimension */
    embeddingDimension?: number | null;
    /** Expectedrevision */
    expectedRevision: number;
    /** Maxoutputtokens */
    maxOutputTokens?: number | null;
    /** Modelname */
    modelName?: string | null;
    modelType?: ModelType | null;
  };

  type ValidationError = {
    /** Context */
    ctx?: Record<string, any>;
    /** Input */
    input?: any;
    /** Location */
    loc: (string | number)[];
    /** Message */
    msg: string;
    /** Error Type */
    type: string;
  };

  type VerificationStatus = "untested" | "passed" | "failed" | "stale";
}
