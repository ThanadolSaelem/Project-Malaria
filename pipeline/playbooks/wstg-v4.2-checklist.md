# OWASP Web Security Testing Guide (WSTG) v4.2 Checklist

> Converted from `WSTG-Checklist_v4.2.xlsx` · 12 categories · 97 test cases

## Contents

1. [Status Legend](#status-legend)
2. [Progress Overview](#progress-overview)
3. [Testing Checklist](#testing-checklist)
   - [Information Gathering](#information-gathering)
   - [Configuration and Deploy Management Testing](#configuration-and-deploy-management-testing)
   - [Identity Management Testing](#identity-management-testing)
   - [Authentication Testing](#authentication-testing)
   - [Authorization Testing](#authorization-testing)
   - [Session Management Testing](#session-management-testing)
   - [Data Validation Testing](#data-validation-testing)
   - [Error Handling](#error-handling)
   - [Cryptography](#cryptography)
   - [Business logic Testing](#business-logic-testing)
   - [Client Side Testing](#client-side-testing)
   - [API Testing](#api-testing)
4. [Summary Findings](#summary-findings)
5. [Risk Assessment Calculator](#risk-assessment-calculator)

---

## Status Legend

| Icon | Status | Meaning |
|:---:|---|---|
| ⬜ | Not Started | Not tested yet |
| ✅ | Pass | Tested, no issue found |
| ⚠️ | Issues | Tested, issue found (log it in Summary Findings) |
| ➖ | N/A | Not applicable to the target |

## Progress Overview

| # | Category | Prefix | Tests | ⬜ | ✅ | ⚠️ | ➖ |
|:---:|---|---|:---:|:---:|:---:|:---:|:---:|
| 1 | [Information Gathering](#information-gathering) | `WSTG-INFO` | 10 | 10 | 0 | 0 | 0 |
| 2 | [Configuration and Deploy Management Testing](#configuration-and-deploy-management-testing) | `WSTG-CONF` | 11 | 11 | 0 | 0 | 0 |
| 3 | [Identity Management Testing](#identity-management-testing) | `WSTG-IDNT` | 5 | 5 | 0 | 0 | 0 |
| 4 | [Authentication Testing](#authentication-testing) | `WSTG-ATHN` | 10 | 10 | 0 | 0 | 0 |
| 5 | [Authorization Testing](#authorization-testing) | `WSTG-ATHZ` | 4 | 4 | 0 | 0 | 0 |
| 6 | [Session Management Testing](#session-management-testing) | `WSTG-SESS` | 9 | 9 | 0 | 0 | 0 |
| 7 | [Data Validation Testing](#data-validation-testing) | `WSTG-INPV` | 19 | 19 | 0 | 0 | 0 |
| 8 | [Error Handling](#error-handling) | `WSTG-ERRH` | 2 | 2 | 0 | 0 | 0 |
| 9 | [Cryptography](#cryptography) | `WSTG-CRYP` | 4 | 4 | 0 | 0 | 0 |
| 10 | [Business logic Testing](#business-logic-testing) | `WSTG-BUSL` | 9 | 9 | 0 | 0 | 0 |
| 11 | [Client Side Testing](#client-side-testing) | `WSTG-CLNT` | 13 | 13 | 0 | 0 | 0 |
| 12 | [API Testing](#api-testing) | `WSTG-APIT` | 1 | 1 | 0 | 0 | 0 |
| | **Total** | | **97** | **97** | **0** | **0** | **0** |

---

## Testing Checklist

### Information Gathering

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-INFO-01` | **Conduct Search Engine Discovery Reconnaissance for Information Leakage** | • Identify what sensitive design and configuration information of the application, system, or organization is exposed directly (on the organization's website) or indirectly (via third-party services). | ⬜ Not Started |  |
| `WSTG-INFO-02` | **Fingerprint Web Server** | • Determine the version and type of a running web server to enable further discovery of any known vulnerabilities. | ⬜ Not Started |  |
| `WSTG-INFO-03` | **Review Webserver Metafiles for Information Leakage** | • Identify hidden or obfuscated paths and functionality through the analysis of metadata files.<br>• Extract and map other information that could lead to better understanding of the systems at hand. | ⬜ Not Started |  |
| `WSTG-INFO-04` | **Enumerate Applications on Webserver** | • Enumerate the applications within scope that exist on a web server. | ⬜ Not Started |  |
| `WSTG-INFO-05` | **Review Webpage Content for Information Leakage** | • Review webpage comments and metadata to find any information leakage.<br>• Gather JavaScript files and review the JS code to better understand the application and to find any information leakage.<br>• Identify if source map files or other front-end debug files exist. | ⬜ Not Started |  |
| `WSTG-INFO-06` | **Identify application entry points** | • Identify possible entry and injection points through request and response analysis. | ⬜ Not Started |  |
| `WSTG-INFO-07` | **Map execution paths through application** | • Map the target application and understand the principal workflows. | ⬜ Not Started |  |
| `WSTG-INFO-08` | **Fingerprint Web Application Framework** | • Fingerprint the components being used by the web applications. | ⬜ Not Started |  |
| `WSTG-INFO-09` | **Fingerprint Web Application** | _(not specified in source)_ | ⬜ Not Started |  |
| `WSTG-INFO-10` | **Map Application Architecture** | • Generate a map of the application at hand based on the research conducted. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Configuration and Deploy Management Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-CONF-01` | **Test Network Infrastructure Configuration** | • Review the applications' configurations set across the network and validate that they are not vulnerable.<br>• Validate that used frameworks and systems are secure and not susceptible to known vulnerabilities due to unmaintained software or default settings and credentials. | ⬜ Not Started |  |
| `WSTG-CONF-02` | **Test Application Platform Configuration** | • Ensure that defaults and known files have been removed.<br>• Validate that no debugging code or extensions are left in the production environments.<br>• Review the logging mechanisms set in place for the application. | ⬜ Not Started |  |
| `WSTG-CONF-03` | **Test File Extensions Handling for Sensitive Information** | • Dirbust sensitive file extensions, or extensions that might contain raw data (*e.g.* scripts, raw data, credentials, etc.).<br>• Validate that no system framework bypasses exist on the rules set. | ⬜ Not Started |  |
| `WSTG-CONF-04` | **Review Old Backup and Unreferenced Files for Sensitive Information** | • Find and analyse unreferenced files that might contain sensitive information. | ⬜ Not Started |  |
| `WSTG-CONF-05` | **Enumerate Infrastructure and Application Admin Interfaces** | • Identify hidden administrator interfaces and functionality. | ⬜ Not Started |  |
| `WSTG-CONF-06` | **Test HTTP Methods** | • Enumerate supported HTTP methods.<br>• Test for access control bypass.<br>• Test XST vulnerabilities.<br>• Test HTTP method overriding techniques. | ⬜ Not Started |  |
| `WSTG-CONF-07` | **Test HTTP Strict Transport Security** | • Review the HSTS header and its validity. | ⬜ Not Started |  |
| `WSTG-CONF-08` | **Test RIA cross domain policy** | • Review and validate the policy files. | ⬜ Not Started |  |
| `WSTG-CONF-09` | **Test File Permission** | • Review and identify any rogue file permissions. | ⬜ Not Started |  |
| `WSTG-CONF-10` | **Test for Subdomain Takeover** | • Enumerate all possible domains (previous and current).<br>• Identify forgotten or misconfigured domains. | ⬜ Not Started |  |
| `WSTG-CONF-11` | **Test Cloud Storage** | • Assess that the access control configuration for the storage services is properly in place. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Identity Management Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-IDNT-01` | **Test Role Definitions** | • Identify and document roles used by the application.<br>• Attempt to switch, change, or access another role.<br>• Review the granularity of the roles and the needs behind the permissions given. | ⬜ Not Started |  |
| `WSTG-IDNT-02` | **Test User Registration Process** | • Verify that the identity requirements for user registration are aligned with business and security requirements.<br>• Validate the registration process. | ⬜ Not Started |  |
| `WSTG-IDNT-03` | **Test Account Provisioning Process** | • Verify which accounts may provision other accounts and of what type. | ⬜ Not Started |  |
| `WSTG-IDNT-04` | **Testing for Account Enumeration and Guessable User Account** | • Review processes that pertain to user identification (*e.g.* registration, login, etc.).<br>• Enumerate users where possible through response analysis. | ⬜ Not Started |  |
| `WSTG-IDNT-05` | **Testing for Weak or unenforced username policy** | • Determine whether a consistent account name structure renders the application vulnerable to account enumeration.<br>• Determine whether the application's error messages permit account enumeration. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Authentication Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-ATHN-01` | **Testing for Credentials Transported over an Encrypted Channel** | • Assess whether any use case of the web site or application causes the server or the client to exchange credentials without encryption. | ⬜ Not Started |  |
| `WSTG-ATHN-02` | **Testing for Default Credentials** | • Enumerate the applications for default credentials and validate if they still exist.<br>• Review and assess new user accounts and if they are created with any defaults or identifiable patterns. | ⬜ Not Started |  |
| `WSTG-ATHN-03` | **Testing for Weak Lock Out Mechanism** | • Evaluate the account lockout mechanism's ability to mitigate brute force password guessing.<br>• Evaluate the unlock mechanism's resistance to unauthorized account unlocking. | ⬜ Not Started |  |
| `WSTG-ATHN-04` | **Testing for Bypassing Authentication Schema** | • Ensure that authentication is applied across all services that require it. | ⬜ Not Started |  |
| `WSTG-ATHN-05` | **Testing for Vulnerable Remember Password** | • Validate that the generated session is managed securely and do not put the user's credentials in danger. | ⬜ Not Started |  |
| `WSTG-ATHN-06` | **Testing for Browser Cache Weaknesses** | • Review if the application stores sensitive information on the client side.<br>• Review if access can occur without authorization. | ⬜ Not Started |  |
| `WSTG-ATHN-07` | **Testing for Weak Password Policy** | • Determine the resistance of the application against brute force password guessing using available password dictionaries by evaluating the length, complexity, reuse, and aging requirements of passwords. | ⬜ Not Started |  |
| `WSTG-ATHN-08` | **Testing for Weak Security Question Answer** | • Determine the complexity and how straight-forward the questions are.<br>• Assess possible user answers and brute force capabilities. | ⬜ Not Started |  |
| `WSTG-ATHN-09` | **Testing for Weak Password Change or Reset Functionalities** | • Determine the resistance of the application to subversion of the account change process allowing someone to change the password of an account.<br>• Determine the resistance of the passwords reset functionality against guessing or bypassing. | ⬜ Not Started |  |
| `WSTG-ATHN-10` | **Testing for Weaker Authentication in Alternative Channel** | • Identify alternative authentication channels.<br>• Assess the security measures used and if any bypasses exists on the alternative channels. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Authorization Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-ATHZ-01` | **Testing Directory Traversal File Include** | • Identify injection points that pertain to path traversal.<br>• Assess bypassing techniques and identify the extent of path traversal. | ⬜ Not Started |  |
| `WSTG-ATHZ-02` | **Testing for Bypassing Authorization Schema** | • Assess if horizontal or vertical access is possible. | ⬜ Not Started |  |
| `WSTG-ATHZ-03` | **Testing for Privilege Escalation** | • Identify injection points related to privilege manipulation.<br>• Fuzz or otherwise attempt to bypass security measures. | ⬜ Not Started |  |
| `WSTG-ATHZ-04` | **Testing for Insecure Direct Object References** | • Identify points where object references may occur.<br>• Assess the access control measures and if they're vulnerable to IDOR. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Session Management Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-SESS-01` | **Testing for Session Management Schema** | • Gather session tokens, for the same user and for different users where possible.<br>• Analyze and ensure that enough randomness exists to stop session forging attacks.<br>• Modify cookies that are not signed and contain information that can be manipulated. | ⬜ Not Started |  |
| `WSTG-SESS-02` | **Testing for Cookies Attributes** | • Ensure that the proper security configuration is set for cookies. | ⬜ Not Started |  |
| `WSTG-SESS-03` | **Testing for Session Fixation** | • Analyze the authentication mechanism and its flow.<br>• Force cookies and assess the impact. | ⬜ Not Started |  |
| `WSTG-SESS-04` | **Testing for Exposed Session Variables** | • Ensure that proper encryption is implemented.<br>• Review the caching configuration.<br>• Assess the channel and methods' security. | ⬜ Not Started |  |
| `WSTG-SESS-05` | **Testing for Cross Site Request Forgery** | • Determine whether it is possible to initiate requests on a user's behalf that are not initiated by the user. | ⬜ Not Started |  |
| `WSTG-SESS-06` | **Testing for Logout Functionality** | • Assess the logout UI.<br>• Analyze the session timeout and if the session is properly killed after logout. | ⬜ Not Started |  |
| `WSTG-SESS-07` | **Testing Session Timeout** | • Validate that a hard session timeout exists. | ⬜ Not Started |  |
| `WSTG-SESS-08` | **Testing for Session Puzzling** | • Identify all session variables.<br>• Break the logical flow of session generation. | ⬜ Not Started |  |
| `WSTG-SESS-09` | **Testing for Session Hijacking** | • Identify vulnerable session cookies.<br>• Hijack vulnerable cookies and assess the risk level. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Data Validation Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-INPV-01` | **Testing for Reflected Cross Site Scripting** | • Identify variables that are reflected in responses.<br>• Assess the input they accept and the encoding that gets applied on return (if any). | ⬜ Not Started |  |
| `WSTG-INPV-02` | **Testing for Stored Cross Site Scripting** | • Identify stored input that is reflected on the client-side.<br>• Assess the input they accept and the encoding that gets applied on return (if any). | ⬜ Not Started |  |
| `WSTG-INPV-03` | **Testing for HTTP Verb Tampering** | _(not specified in source)_ | ⬜ Not Started |  |
| `WSTG-INPV-04` | **Testing for HTTP Parameter Pollution** | • Identify the backend and the parsing method used.<br>• Assess injection points and try bypassing input filters using HPP. | ⬜ Not Started |  |
| `WSTG-INPV-05` | **Testing for SQL Injection** | • Identify SQL injection points.<br>• Assess the severity of the injection and the level of access that can be achieved through it. | ⬜ Not Started |  |
| `WSTG-INPV-06` | **Testing for LDAP Injection** | • Identify LDAP injection points.<br>• Assess the severity of the injection. | ⬜ Not Started |  |
| `WSTG-INPV-07` | **Testing for XML Injection** | • Identify XML injection points.<br>• Assess the types of exploits that can be attained and their severities. | ⬜ Not Started |  |
| `WSTG-INPV-08` | **Testing for SSI Injection** | • Identify SSI injection points.<br>• Assess the severity of the injection. | ⬜ Not Started |  |
| `WSTG-INPV-09` | **Testing for XPath Injection** | • Identify XPATH injection points. | ⬜ Not Started |  |
| `WSTG-INPV-10` | **Testing for IMAP SMTP Injection** | • Identify IMAP/SMTP injection points.<br>• Understand the data flow and deployment structure of the system.<br>• Assess the injection impacts. | ⬜ Not Started |  |
| `WSTG-INPV-11` | **Testing for Code Injection** | • Identify injection points where you can inject code into the application.<br>• Assess the injection severity. | ⬜ Not Started |  |
| `WSTG-INPV-12` | **Testing for Command Injection** | • Identify and assess the command injection points. | ⬜ Not Started |  |
| `WSTG-INPV-13` | **Testing for Format String Injection** | • Assess whether injecting format string conversion specifiers into user-controlled fields causes undesired behaviour from the application. | ⬜ Not Started |  |
| `WSTG-INPV-14` | **Testing for Incubated Vulnerability** | • Identify injections that are stored and require a recall step to the stored injection.<br>• Understand how a recall step could occur.<br>• Set listeners or activate the recall step if possible. | ⬜ Not Started |  |
| `WSTG-INPV-15` | **Testing for HTTP Splitting Smuggling** | • Assess if the application is vulnerable to splitting, identifying what possible attacks are achievable.<br>• Assess if the chain of communication is vulnerable to smuggling, identifying what possible attacks are achievable. | ⬜ Not Started |  |
| `WSTG-INPV-16` | **Testing for HTTP Incoming Requests** | • Monitor all incoming and outgoing HTTP requests to the Web Server to inspect any suspicious requests.<br>• Monitor HTTP traffic without changes of end user Browser proxy or client-side application. | ⬜ Not Started |  |
| `WSTG-INPV-17` | **Testing for Host Header Injection** | • Assess if the Host header is being parsed dynamically in the application.<br>• Bypass security controls that rely on the header. | ⬜ Not Started |  |
| `WSTG-INPV-18` | **Testing for Server-side Template Injection** | • Detect template injection vulnerability points.<br>• Identify the templating engine.<br>• Build the exploit. | ⬜ Not Started |  |
| `WSTG-INPV-19` | **Testing for Server-Side Request Forgery** | • Identify SSRF injection points.<br>• Test if the injection points are exploitable.<br>• Assess the severity of the vulnerability. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Error Handling

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-ERRH-01` | **Testing for Improper Error Handling** | • Identify existing error output.<br>• Analyze the different output returned. | ⬜ Not Started |  |
| `WSTG-ERRH-02` | **Testing for Stack Traces** | _(not specified in source)_ | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Cryptography

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-CRYP-01` | **Testing for Weak Transport Layer Security** | • Validate the service configuration.<br>• Review the digital certificate's cryptographic strength and validity.<br>• Ensure that the TLS security is not bypassable and is properly implemented across the application. | ⬜ Not Started |  |
| `WSTG-CRYP-02` | **Testing for Padding Oracle** | • Identify encrypted messages that rely on padding.<br>• Attempt to break the padding of the encrypted messages and analyze the returned error messages for further analysis. | ⬜ Not Started |  |
| `WSTG-CRYP-03` | **Testing for Sensitive Information Sent via Unencrypted Channels** | • Identify sensitive information transmitted through the various channels.<br>• Assess the privacy and security of the channels used. | ⬜ Not Started |  |
| `WSTG-CRYP-04` | **Testing for Weak Encryption** | • Provide a guideline for the identification weak encryption or hashing uses and implementations. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Business logic Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-BUSL-01` | **Test Business Logic Data Validation** | • Identify data injection points.<br>• Validate that all checks are occurring on the back end and can't be bypassed.<br>• Attempt to break the format of the expected data and analyze how the application is handling it. | ⬜ Not Started |  |
| `WSTG-BUSL-02` | **Test Ability to Forge Requests** | • Review the project documentation looking for guessable, predictable, or hidden functionality of fields.<br>• Insert logically valid data in order to bypass normal business logic workflow. | ⬜ Not Started |  |
| `WSTG-BUSL-03` | **Test Integrity Checks** | • Review the project documentation for components of the system that move, store, or handle data.<br>• Determine what type of data is logically acceptable by the component and what types the system should guard against.<br>• Determine who should be allowed to modify or read that data in each component.<br>• Attempt to insert, update, or delete data values used by each component that should not be allowed per the business logic workflow. | ⬜ Not Started |  |
| `WSTG-BUSL-04` | **Test for Process Timing** | • Review the project documentation for system functionality that may be impacted by time.<br>• Develop and execute misuse cases. | ⬜ Not Started |  |
| `WSTG-BUSL-05` | **Test Number of Times a Function Can be Used Limits** | • Identify functions that must set limits to the times they can be called.<br>• Assess if there is a logical limit set on the functions and if it is properly validated. | ⬜ Not Started |  |
| `WSTG-BUSL-06` | **Testing for the Circumvention of Work Flows** | • Review the project documentation for methods to skip or go through steps in the application process in a different order from the intended business logic flow.<br>• Develop a misuse case and try to circumvent every logic flow identified. | ⬜ Not Started |  |
| `WSTG-BUSL-07` | **Test Defenses Against Application Mis-use** | • Generate notes from all tests conducted against the system.<br>• Review which tests had a different functionality based on aggressive input.<br>• Understand the defenses in place and verify if they are enough to protect the system against bypassing techniques. | ⬜ Not Started |  |
| `WSTG-BUSL-08` | **Test Upload of Unexpected File Types** | • Review the project documentation for file types that are rejected by the system.<br>• Verify that the unwelcomed file types are rejected and handled safely.<br>• Verify that file batch uploads are secure and do not allow any bypass against the set security measures. | ⬜ Not Started |  |
| `WSTG-BUSL-09` | **Test Upload of Malicious Files** | • Identify the file upload functionality.<br>• Review the project documentation to identify what file types are considered acceptable, and what types would be considered dangerous or malicious.<br>• Determine how the uploaded files are processed.<br>• Obtain or create a set of malicious files for testing.<br>• Try to upload the malicious files to the application and determine whether it is accepted and processed. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### Client Side Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-CLNT-01` | **Testing for DOM-Based Cross Site Scripting** | • Identify DOM sinks.<br>• Build payloads that pertain to every sink type. | ⬜ Not Started |  |
| `WSTG-CLNT-02` | **Testing for JavaScript Execution** | • Identify sinks and possible JavaScript injection points. | ⬜ Not Started |  |
| `WSTG-CLNT-03` | **Testing for HTML Injection** | • Identify HTML injection points and assess the severity of the injected content. | ⬜ Not Started |  |
| `WSTG-CLNT-04` | **Testing for Client Side URL Redirect** | • Identify injection points that handle URLs or paths.<br>• Assess the locations that the system could redirect to. | ⬜ Not Started |  |
| `WSTG-CLNT-05` | **Testing for CSS Injection** | • Identify CSS injection points.<br>• Assess the impact of the injection. | ⬜ Not Started |  |
| `WSTG-CLNT-06` | **Testing for Client Side Resource Manipulation** | • Identify sinks with weak input validation.<br>• Assess the impact of the resource manipulation. | ⬜ Not Started |  |
| `WSTG-CLNT-07` | **Test Cross Origin Resource Sharing** | • Identify endpoints that implement CORS.<br>• Ensure that the CORS configuration is secure or harmless. | ⬜ Not Started |  |
| `WSTG-CLNT-08` | **Testing for Cross Site Flashing** | • Decompile and analyze the application's code.<br>• Assess sinks inputs and unsafe method usages. | ⬜ Not Started |  |
| `WSTG-CLNT-09` | **Testing for Clickjacking** | • Understand security measures in place.<br>• Assess how strict the security measures are and if they are bypassable. | ⬜ Not Started |  |
| `WSTG-CLNT-10` | **Testing WebSockets** | • Identify the usage of WebSockets.<br>• Assess its implementation by using the same tests on normal HTTP channels. | ⬜ Not Started |  |
| `WSTG-CLNT-11` | **Test Web Messaging** | • Assess the security of the message's origin.<br>• Validate that it's using safe methods and validating its input. | ⬜ Not Started |  |
| `WSTG-CLNT-12` | **Testing Browser Storage** | • Determine whether the website is storing sensitive data in client-side storage.<br>• The code handling of the storage objects should be examined for possibilities of injection attacks, such as utilizing unvalidated input or vulnerable libraries. | ⬜ Not Started |  |
| `WSTG-CLNT-13` | **Testing for Cross Site Script Inclusion** | • Locate sensitive data across the system.<br>• Assess the leakage of sensitive data through various techniques. | ⬜ Not Started |  |

[↑ Back to top](#contents)

### API Testing

| ID | Test Name | Objectives | Status | Notes |
|---|---|---|:---:|---|
| `WSTG-APIT-01` | **Testing GraphQL** | • Assess that a secure and production-ready configuration is deployed.<br>• Validate all input fields against generic attacks.<br>• Ensure that proper access controls are applied. | ⬜ Not Started |  |

[↑ Back to top](#contents)

---

## Summary Findings

Template for logging findings (row 1 is the example from the source file).

| No. | Vulnerability Name | WSTG ID | Affected Host/Path | Impact | Likelihood | Risk | Observation/Implication | Recommendation | Test Evidence |
|:---:|---|---|---|---|---|---|---|---|---|
| 1 | SQL Injection | `WSTG-INPV-05` | www.example.com/news.php (id,page) | High | Moderate | High |  |  | xxx-1 |
| | | | | | | | | | |

---

## Risk Assessment Calculator

Based on the **OWASP Risk Rating Methodology**. Choose one option per factor; each option carries a score from 0 to 9.

- **Likelihood score** = average of the 8 likelihood factors
- **Impact score** = average of the 8 impact factors
- Score ranges: `0 to <3` = Low · `3 to <6` = Moderate · `6 to 9` = High

### Likelihood Factors

#### Threat Agent Factors

| Factor | Options (score) | Example selection |
|---|---|---|
| **Skills required** | Not Applicable **(0)**<br>No technical skills **(1)**<br>Some technical skills **(3)**<br>Advanced computer user **(5)**<br>Network and programming skills **(6)**<br>Security penetration skills **(9)** | Some technical skills → **3** |
| **Motive** | Not Applicable **(0)**<br>Low or no reward **(1)**<br>Possible reward **(4)**<br>High reward **(9)** | Possible reward → **4** |
| **Opportunity** | Full access or expensive resources required **(0)**<br>Special access or resources required **(4)**<br>Some access or resources required **(7)**<br>No access or resources required **(9)** | Full access or expensive resources required → **0** |
| **Population Size** | Not Applicable **(0)**<br>System Administrators **(2)**<br>Intranet Users **(4)**<br>Partners **(5)**<br>Authenticated users **(6)**<br>Anonymous Internet users **(9)** | System Administrators → **2** |

#### Vulnerability Factors

| Factor | Options (score) | Example selection |
|---|---|---|
| **Ease of Discovery** | Not Applicable **(0)**<br>Practically impossible **(1)**<br>Difficult **(3)**<br>Easy **(7)**<br>Automated tools available **(9)** | Practically impossible → **1** |
| **Ease of Exploit** | Not Applicable **(0)**<br>Theoretical **(1)**<br>Difficult **(3)**<br>Easy **(5)**<br>Automated tools available **(9)** | Easy → **5** |
| **Awareness** | Not Applicable **(0)**<br>Unknown **(1)**<br>Hidden **(4)**<br>Obvious **(6)**<br>Public knowledge **(9)** | Hidden → **4** |
| **Intrusion Detection** | Not Applicable **(0)**<br>Active detection in application **(1)**<br>Logged and reviewed **(3)**<br>Logged without review **(8)**<br>Not logged **(9)** | Logged and reviewed → **3** |

### Impact Factors

#### Technical Impact Factors

| Factor | Options (score) | Example selection |
|---|---|---|
| **Loss of confidentiality** | Not Applicable **(0)**<br>Minimal non-sensitive data disclosed **(2)**<br>Extensive non-sensitive data disclosed **(6)**<br>Extensive critical data disclosed **(7)**<br>All data disclosed **(9)** | Minimal non-sensitive data disclosed → **2** |
| **Loss of Integrity** | Not Applicable **(0)**<br>Minimal slightly corrupt data **(1)**<br>Minimal seriously corrupt data **(3)**<br>Extensive slightly corrupt data **(5)**<br>Extensive seriously corrupt data **(7)**<br>All data totally corrupt **(9)** | All data totally corrupt → **9** |
| **Loss of Availability** | Not Applicable **(0)**<br>Minimal secondary services interrupted **(1)**<br>Minimal primary services interrupted **(5)**<br>Extensive primary services interrupted **(7)**<br>All services completely lost **(9)** | Minimal secondary services interrupted → **1** |
| **Loss of Accountability** | Not Applicable **(0)**<br>Attack fully traceable to individual **(1)**<br>Attack possibly traceable to individual **(7)**<br>Attack completely anonymous **(9)** | Not Applicable → **0** |

#### Business Impact Factors

| Factor | Options (score) | Example selection |
|---|---|---|
| **Financial damage** | Not Applicable **(0)**<br>Damage costs less than to fix the issue **(1)**<br>Minor effect on annual profit **(3)**<br>Significant effect on annual profit **(7)**<br>Bankruptcy **(9)** | Minor effect on annual profit → **3** |
| **Reputation damage** | Not Applicable **(0)**<br>Minimal damage **(1)**<br>Loss of major accounts **(4)**<br>Loss of goodwill **(5)**<br>Brand damage **(9)** | Loss of major accounts → **4** |
| **Non-Compliance** | Not Applicable **(0)**<br>Minor violation **(2)**<br>Clear violation **(5)**<br>High profile violation **(7)** | Clear violation → **5** |
| **Privacy violation** | Not Applicable **(0)**<br>One individual **(3)**<br>Hundreds of people **(5)**<br>Thousands of people **(7)**<br>Millions of people **(9)** | One individual → **3** |

### Example Result (from source file)

| Metric | Value |
|---|:---:|
| Likelihood score | **2.75** (Low) |
| Impact score | **3.375** (Moderate) |
| Overall Risk Severity | **Low** |

### Overall Risk Severity Matrix

| Impact ↓ / Likelihood → | Low | Moderate | High |
|---|:---:|:---:|:---:|
| **High** | 🟠 Moderate | 🔴 High | 🟣 Critical |
| **Moderate** | 🟢 Low | 🟠 Moderate | 🔴 High |
| **Low** | ⚪ Note | 🟢 Low | 🟠 Moderate |

[↑ Back to top](#contents)
