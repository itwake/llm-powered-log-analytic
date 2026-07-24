
# Presentation Script: LogAn Project

## Opening

Hello everyone.

Today I will introduce **LogAn**, an LLM-powered log analysis platform.

LogAn is made for support teams, SRE teams, and development teams. When a system incident happens, users can create a case, upload log files, start an analysis, and review the result in five connected views.

These five views are:

* Data Summary
* Temporal View
* Tabular Logs
* Causal Graph
* Causal Summary

The main goal of the project is to turn a large number of raw log lines into a smaller and clearer incident story. At the same time, every result can be traced back to the original log file and line.

Today, I will cover four topics:

First, the project structure.
Second, the infrastructure deployment.
Third, the core log analysis process.
And finally, what has not been completed yet.

*资料依据，不朗读：项目定位、使用流程和五个视图来自项目 README。*

---

# 1. The Project Structure

First, let us look at the project structure.

LogAn is a **monorepo**. A monorepo means that the backend, the analysis engine, the frontend, the deployment files, and the tests are all kept in one repository.

There are three main application folders.

### The API application

The first folder is `apps/api`.

This is the backend and the control center of the system. It is built with FastAPI and Python.

It handles:

* SSO login and user sessions
* User roles and case access
* Case creation
* File upload
* Analysis run creation
* Report APIs
* Chat
* Admin functions
* Data retention

The API does not contain most of the log analysis math. Its main job is to control the process, protect the data, store the state, and provide data to the frontend.

Inside this folder, `main.py` starts the application. The `api` folder contains the API routes. The `services` folder contains services for object storage, SSO, the model gateway, and external analytics systems.

The project has one metadata-store implementation: SQLAlchemy over SQLite or PostgreSQL. Tests use that same implementation with an isolated in-memory SQLite database.

### The worker application

The second folder is `apps/workers`.

This is the analysis engine.

It contains the main pipeline in `pipeline.py`. It also contains the Temporal worker, the log-processing algorithms, the model prompts, and the offline benchmark tools.

The `activities` folder has one small module for each pipeline step.

The `algorithms` folder has the main processing logic, such as:

* Log parsing
* Sensitive-data hiding
* Multi-line log merging
* Drain-style log templates
* Sampling
* Causal scoring
* PageRank

The `prompts` folder contains the instructions sent to the model.

The `evaluation` folder contains benchmark code. It checks whether a code change makes the analysis better or worse.

### The web application

The third folder is `apps/web`.

This is the user interface. It is built with Next.js, React, and TypeScript.

The web application lets users sign in, create cases, upload files, start an analysis, see progress, and open the five report views.

It uses Apache ECharts for the time chart. It uses Cytoscape.js for the causal graph.

Inside the web source folder, `app` contains the pages, `components` contains shared user-interface parts, and `lib` contains API, authentication, formatting, and navigation helpers.

### The supporting folders

There are also several supporting folders.

The `infra` folder contains Docker and Kubernetes deployment files.

The `tests` folder contains backend, worker, integration, and browser tests.

The `benchmarks` folder contains a known test incident and its expected results.

The `scripts` folder contains local startup, demo-data, migration, smoke-test, and screenshot scripts.

The `docs` folder contains architecture, operations, security, data-model, and demo documents.

The `.github` folder contains the CI workflow files.

So, in one simple sentence, the main flow is:

**The browser talks to the web application. The web application talks to the API. The API controls the analysis worker. The worker creates the results, and the web application shows them to the user.**

*资料依据，不朗读：仓库根目录及三个运行部分见项目结构；API 和 worker 的详细目录来自各自 README。* ([GitHub][1])

---

# 2. The Infrastructure Deployment

Next, I will explain the infrastructure deployment.

The project supports several deployment levels. We can understand them from simple to complex.

## Local development

The simplest option is local development.

On Windows, we can run `scripts\local.ps1` or `scripts\local.bat`.

This starts two processes:

* The API on port 8000
* The web application on port 3000

The default local setup uses SQLite for case and result data. It uses the local file system for uploaded files. It uses a mock SSO provider, so no real login system is needed.

It also uses a mock LLM provider. This mock provider gives the same result every time. This is useful for local development, tests, and demos.

No PostgreSQL, MinIO, Temporal, ClickHouse, or OpenSearch service is required for this mode.

## Quick Docker deployment

The second option is the quick Docker setup.

The file is `docker-compose.quickstart.yml`.

This setup contains only two containers:

* API
* Web

The API still uses SQLite, local file storage, mock SSO, and the mock model. A Docker volume keeps the case data after a container restart.

This option is useful when we want a simple demo but do not want to install Python and Node.js directly on the machine.

## Full Docker Compose deployment

The third option is the full Docker Compose stack.

This is closer to a production system.

The main application services are:

* The Next.js web application
* The FastAPI service
* The Temporal analysis worker

The main data and support services are:

* PostgreSQL
* MinIO
* Temporal
* ClickHouse
* OpenSearch

PostgreSQL stores case data, user data, job events, and normalized analysis results.

MinIO acts like S3. It stores uploaded log files and pipeline step manifests.

Temporal controls long-running analysis jobs. The API starts a workflow, and a worker takes the job from the Temporal task queue.

ClickHouse can store time-window data. OpenSearch can store searchable log rows. These two systems are optional analytics stores. The normal report path can still use PostgreSQL, and the API can fall back to SQL when an external query fails.

The Docker stack also defines health checks and persistent volumes. This means each service can be checked before another service starts, and important data can survive a restart.

## Kubernetes deployment

The fourth option is Kubernetes.

The Kubernetes files are under `infra/k8s`.

The project has separate deployments for the API, web application, and worker.

The API and web application each have a Kubernetes Service. The worker does not need a Service because it is not an HTTP server. It connects to Temporal and waits for jobs.

An Ingress sends `/api` traffic to the API service. All other traffic goes to the web service.

Configuration is loaded from a ConfigMap and a Secret. There is also a migration job, network policy, health probes, and horizontal auto-scaling.

The default Kubernetes files start with two API pods, two web pods, and two worker pods. The API can scale from two to eight pods. The worker can scale from two to ten pods based on CPU use.

In a real production deployment, example domains, image tags, SSO addresses, database passwords, object-store keys, and AI Platform credentials must be replaced with real values.

So the production-shaped request flow is:

**User to Ingress, Ingress to web or API, API to PostgreSQL and object storage, API to Temporal, Temporal to the worker, and the worker back to the data stores.**

*资料依据，不朗读：快速 Docker 模式只有 API、Web 和本地数据卷；完整 Compose 定义 API、Web、Worker、PostgreSQL、MinIO、Temporal、ClickHouse 与 OpenSearch；Kubernetes 清单定义独立部署、Ingress 和自动扩缩。*

---

# 3. The Core Log Analysis Process

Now let us look at the most important part: the log analysis process.

The code has ten named analysis steps, followed by one export step. In total, the pipeline makes eleven step calls.

## Step 1: Upload and start an analysis

First, a user creates a case and uploads log files.

The files can be normal log files, JSONL files, gzip files, or zip files.

The API stores the file data in the local object store or in S3 or MinIO. It also creates a database record for each file.

When the user starts an analysis, the API creates an analysis-run record.

In local mode, the API runs the pipeline directly.

In Temporal mode, the API sends the job to Temporal, and a worker runs the same pipeline.

## Step 2: Ingest the files

The pipeline reads each file line by line.

For every log line, it keeps important source information, including:

* File path
* Line number
* Time
* A SHA-256 hash
* The original text

This information gives every log line a stable identity.

## Step 3: Merge multi-line entries

Some errors use more than one physical line.

A Java stack trace is a common example.

The pipeline joins these lines into one logical log entry. At the same time, it keeps links to all original lines.

This stops one error from being counted as many separate messages.

## Step 4: Parse, normalize, and hide sensitive data

Next, the pipeline reads fields such as:

* Timestamp
* Log level
* Service name
* Message text

Then it hides sensitive values.

For example, it can hide:

* Email addresses
* IP addresses
* Passwords
* Tokens
* API keys
* JWTs
* UUIDs
* Card-like values
* Customer or tenant IDs

This hiding step happens before any log text is sent to a model.

## Step 5: Create log templates

The pipeline then groups similar log lines into templates.

Values that often change, such as request IDs, user IDs, status numbers, and time values, are replaced by a marker such as `<*>`.

For example, two checkout errors with different request IDs can become one template.

This is an important compression step. Instead of asking the model to read thousands of lines, the system can work with a much smaller number of log patterns.

## Step 6: Select representative samples

For each template, the pipeline chooses a small number of sample lines.

By default, it can choose up to five samples for each template.

These samples are already cleaned and redacted.

The model never receives every raw log line. It receives only these small representative samples.

## Step 7: Ask the model for an annotation

The model receives:

* The template
* The redacted samples
* Safe case information

It then returns labels such as:

* Golden signal
* Fault category
* Service or other entities
* Severity
* Confidence
* A short reason

A golden signal can be error, availability, latency, saturation, traffic, information, or unknown.

In local mode, the project can use a rule-based mock model. On the supported real-model path, it can use the AI Platform gateway.

## Step 8: Copy labels to all matching lines

The model only reads the samples, but its result is copied back to every line in the same template group.

This means a line can receive a useful label even when that exact line was not sent to the model.

These enriched lines are shown in the Tabular Logs view.

## Step 9: Build the time view

The pipeline groups enriched lines into time windows. The default window is 60 seconds.

It counts events by time, service, signal, fault category, and template.

These counts become the Temporal View.

When a user clicks a time window, the web application can open the matching rows in Tabular Logs.

## Step 10: Build the causal graph

Next, the system creates a graph of possible cause-and-effect links.

Problem templates become nodes. The pipeline checks possible links between these nodes.

It asks questions such as:

* Did one event start before another event?
* Did the second event happen more often when the first event was active?
* Are the two time series connected with a delay?
* Do earlier source counts help predict later target counts?

The code uses temporal order, lift, lagged correlation, PGEM-style scoring, Granger-style scoring, and PageRank-style ranking.

However, the graph does not claim that a cause is proven.

Every edge is marked as a **candidate cause**, and it has a `needs_validation` flag.

The graph tells an engineer what to check first. The engineer should still confirm the result with metrics, traces, deployments, and system knowledge.

## Step 11: Create the summary and exports

Finally, the pipeline builds a small evidence packet from the graph, the templates, the time windows, and the redacted log evidence.

The model uses this packet to create a cautious causal summary.

The summary can contain:

* A leading root-cause candidate
* The possible event chain
* Evidence references
* Uncertainty
* Suggested next actions
* A customer-safe update

When the model is not available, the system creates a rule-based fallback summary.

The analysis can then be exported as Markdown, HTML, or JSON.

The results are also stored in normalized database tables. Optional copies can be sent to ClickHouse and OpenSearch.

There are two important rules across the whole pipeline.

**Rule one: the model only sees redacted representative samples.**

**Rule two: every important result keeps an evidence reference to the original file and line.**

These two rules give the project both privacy and traceability.

*资料依据，不朗读：完整日志生命周期、敏感信息处理、模板化、抽样、因果图和汇总步骤来自 `life-of-a-log-line.md`；代码中的实际步骤顺序来自 `pipeline.py`。*

---

# 4. What Has Not Been Done Yet

Finally, I will explain what has not been completed yet.

The project already has a large working foundation, but it is not yet a fully finished enterprise product.

## Advanced enterprise access control

Basic SSO, role-based access, policy groups, and SCIM endpoints already exist.

However, the project documents say that more advanced policy groups, fuller user-directory sync, and richer approval flows are still future work.

For example, a large company may need more detailed approval rules before a user can access a case or export incident data.

## More browser end-to-end tests

The project already uses Playwright for browser tests.

However, the documentation says that the end-to-end test coverage should continue to grow as more workflows and visual features are added.

Enterprise flows, unusual upload cases, failure recovery, admin actions, and more complex access rules need wider browser coverage.

## Real model use inside the Temporal worker

This is an important technical gap.

On the local, in-process path, the API can inject the real AI Platform model gateway into the pipeline.

However, the current Temporal activity calls the pipeline without passing a real model gateway. Because of this, it uses the mock gateway by default.

The full-stack Docker smoke test also uses the mock provider.

Before using Temporal for real production inference, the real model gateway should be created inside the worker, passed into the pipeline, and tested with real staging credentials.

## The task execution endpoint

The API contains a `/tasks/execute` endpoint.

At the moment, this endpoint only returns an “accepted” result and a task ID. It does not start a real background task.

So this is still a scaffold, not a complete task execution system.

## Other optional improvements

The architecture document also lists some possible future extensions.

These include:

* Better tuning of the Drain3 integration
* S3 storage for report artifacts
* More native model streaming behavior
* Causal sensitivity reports using different time-window sizes

One more point is important.

The causal graph will still need human validation, even after all planned work is complete. This is not only a missing feature. It is also an intentional safety rule. Logs can show strong evidence, but logs alone cannot always prove the true root cause.

So, the current project is a strong and testable foundation. The main analysis path, user interface, storage, deployment files, security rules, and reports already exist.

The main remaining work is to finish the production model path under Temporal, expand enterprise access workflows, replace scaffold endpoints, and increase end-to-end test coverage.

*资料依据，不朗读：明确列出的剩余工作包括高级策略组、目录同步、审批流程和更多 Playwright 测试；worker 文档和实际代码确认 Temporal activity 尚未注入真实模型 gateway；`tasks/execute` 当前只返回接受状态。*

---

# Closing

To conclude, LogAn has a clear three-part architecture: API, worker, and web application.

It supports simple local use, Docker deployment, and Kubernetes deployment.

Its main value is the log analysis pipeline. It reduces a large log set into templates, time signals, possible causal links, and a readable summary.

At the same time, it protects sensitive data and keeps every conclusion connected to source evidence.

The project is already a strong platform foundation, but a few important production and enterprise features still need more work.

Thank you.
