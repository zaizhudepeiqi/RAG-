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

  type SuccessResponse = {
    /** Success */
    success?: boolean;
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
}
