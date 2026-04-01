# Jenkins Integration Examples

This directory contains examples for integrating the Jenkins Failure Analysis Agent with your CI/CD pipelines.

## Option 1: Full Integration with PR Comments (Recommended)

Add a post-failure stage that updates Jenkins description AND posts to the PR:

```groovy
// Jenkinsfile
pipeline {
    agent any
    
    environment {
        FAILURE_AGENT_URL = 'http://your-agent-server:8080'
        FAILURE_AGENT_API_KEY = credentials('failure-agent-api-key')
    }
    
    stages {
        stage('Build') {
            steps {
                sh 'make build'
            }
        }
        
        stage('Test') {
            steps {
                sh 'make test'
            }
        }
        
        stage('Deploy') {
            steps {
                sh 'make deploy'
            }
        }
    }
    
    post {
        failure {
            script {
                // Get PR info (set by multibranch pipeline or manually)
                def prUrl = env.CHANGE_URL ?: ''
                def prSha = env.GIT_COMMIT ?: ''
                
                // Trigger failure analysis with PR posting
                def response = httpRequest(
                    url: "${FAILURE_AGENT_URL}/analyze",
                    httpMode: 'POST',
                    contentType: 'APPLICATION_JSON',
                    customHeaders: [[name: 'X-API-Key', value: "${FAILURE_AGENT_API_KEY}"]],
                    requestBody: """{
                        "job": "${JOB_NAME}",
                        "build": ${BUILD_NUMBER},
                        "workspace": "${WORKSPACE}",
                        "pr_url": "${prUrl}",
                        "pr_sha": "${prSha}",
                        "update_jenkins_description": true,
                        "post_to_pr": true,
                        "notify_slack": true
                    }"""
                )
                
                def result = readJSON text: response.content
                
                // Display summary in build log
                echo "=== FAILURE ANALYSIS ==="
                echo "Category: ${result.category}"
                echo "Tier: ${result.tier}"
                echo "Root Cause: ${result.root_cause}"
                echo "Confidence: ${result.confidence}"
                echo ""
                echo "Retry Assessment:"
                echo "  Retriable: ${result.is_retriable}"
                echo "  Reason: ${result.retry_reason}"
                echo ""
                echo "Recommendations:"
                result.recommendations.each { rec ->
                    echo "  [${rec.priority}] ${rec.action}"
                }
                echo ""
                echo "Actions Taken:"
                echo "  Jenkins description updated: ${result.jenkins_description_updated}"
                echo "  PR comment posted: ${result.pr_comment_posted}"
                echo "========================"
                
                // Decide whether to retry based on assessment
                if (result.is_retriable && env.BUILD_NUMBER.toInteger() < 3) {
                    echo "Failure is retriable, scheduling retry..."
                    sleep(result.retry_assessment?.recommended_wait_seconds ?: 60)
                    build job: env.JOB_NAME, wait: false
                }
            }
        }
        
        always {
            cleanWs()
        }
    }
}
```

## Option 2: Post-Build Hook (Simple)

Add a post-failure stage to your Jenkinsfile:

```groovy
// Jenkinsfile
pipeline {
    agent any
    
    environment {
        FAILURE_AGENT_URL = 'http://your-agent-server:8080'
        FAILURE_AGENT_API_KEY = credentials('failure-agent-api-key')
    }
    
    stages {
        stage('Build') {
            steps {
                sh 'make build'
            }
        }
        
        stage('Test') {
            steps {
                sh 'make test'
            }
        }
        
        stage('Deploy') {
            steps {
                sh 'make deploy'
            }
        }
    }
    
    post {
        failure {
            script {
                // Trigger failure analysis
                def response = httpRequest(
                    url: "${FAILURE_AGENT_URL}/analyze",
                    httpMode: 'POST',
                    contentType: 'APPLICATION_JSON',
                    customHeaders: [[name: 'X-API-Key', value: "${FAILURE_AGENT_API_KEY}"]],
                    requestBody: """{
                        "job": "${JOB_NAME}",
                        "build": ${BUILD_NUMBER},
                        "workspace": "${WORKSPACE}",
                        "notify_slack": true
                    }"""
                )
                
                def result = readJSON text: response.content
                
                // Display summary in build log
                echo "=== FAILURE ANALYSIS ==="
                echo "Category: ${result.category}"
                echo "Root Cause: ${result.root_cause}"
                echo "Confidence: ${result.confidence}"
                echo ""
                echo "Recommendations:"
                result.recommendations.each { rec ->
                    echo "  [${rec.priority}] ${rec.action}"
                }
                echo "========================"
                
                // Archive the report
                if (result.report_url) {
                    archiveArtifacts artifacts: 'reports/*.md', allowEmptyArchive: true
                }
            }
        }
        
        always {
            // Clean up workspace
            cleanWs()
        }
    }
}
```

## Option 3: Jenkins Webhook Plugin

Configure the Jenkins Notification Plugin to send webhooks to the agent:

1. Install the "Notification Plugin" in Jenkins
2. Go to Job Configuration → Job Notifications
3. Add a notification endpoint:
   - URL: `http://your-agent-server:8080/webhook/jenkins`
   - Event: Job Finalized
   - Protocol: HTTP
   - Format: JSON

The agent will automatically analyze failed builds.

## Option 4: Shared Library

Create a shared library for reusable analysis steps:

```groovy
// vars/analyzeFailure.groovy
def call(Map config = [:]) {
    def agentUrl = config.agentUrl ?: env.FAILURE_AGENT_URL
    def apiKey = config.apiKey ?: env.FAILURE_AGENT_API_KEY
    
    def response = httpRequest(
        url: "${agentUrl}/analyze",
        httpMode: 'POST',
        contentType: 'APPLICATION_JSON',
        customHeaders: [[name: 'X-API-Key', value: apiKey]],
        requestBody: groovy.json.JsonOutput.toJson([
            job: env.JOB_NAME,
            build: env.BUILD_NUMBER as Integer,
            workspace: env.WORKSPACE,
            notify_slack: config.notifySlack ?: false,
            generate_report: config.generateReport ?: true
        ])
    )
    
    return readJSON(text: response.content)
}
```

Usage in Jenkinsfile:

```groovy
@Library('your-shared-library') _

pipeline {
    agent any
    
    stages {
        // ... your stages
    }
    
    post {
        failure {
            script {
                def analysis = analyzeFailure(notifySlack: true)
                echo "Root cause: ${analysis.root_cause}"
            }
        }
    }
}
```

## Option 5: Docker Sidecar

Run the agent as a sidecar container in your Jenkins:

```yaml
# docker-compose.yml for Jenkins + Agent
version: '3.8'

services:
  jenkins:
    image: jenkins/jenkins:lts
    ports:
      - "8080:8080"
    volumes:
      - jenkins_home:/var/jenkins_home
    environment:
      - FAILURE_AGENT_URL=http://failure-agent:8080
  
  failure-agent:
    build: ./jenkins-failure-agent
    ports:
      - "8081:8080"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./reports:/app/reports
    environment:
      - JENKINS_URL=http://jenkins:8080
      - JENKINS_USERNAME=${JENKINS_USERNAME}
      - JENKINS_API_TOKEN=${JENKINS_API_TOKEN}
      - AI_BASE_URL=${AI_BASE_URL}
      - AI_MODEL=${AI_MODEL}
      - AI_API_KEY=${AI_API_KEY}

volumes:
  jenkins_home:
```

## Option 6: CLI in Pipeline

Run the agent CLI directly in your pipeline:

```groovy
pipeline {
    agent {
        docker {
            image 'python:3.11'
        }
    }
    
    stages {
        // ... your stages
    }
    
    post {
        failure {
            sh '''
                pip install -r jenkins-failure-agent/requirements.txt
                python jenkins-failure-agent/agent.py analyze \
                    --job "${JOB_NAME}" \
                    --build ${BUILD_NUMBER} \
                    --workspace "${WORKSPACE}" \
                    --format markdown \
                    --format json
            '''
            archiveArtifacts artifacts: 'reports/*', allowEmptyArchive: true
        }
    }
}
```

## Environment Variables

The agent supports these environment variables for configuration:

| Variable | Description |
|----------|-------------|
| `JENKINS_URL` | Jenkins server URL |
| `JENKINS_USERNAME` | Jenkins username |
| `JENKINS_API_TOKEN` | Jenkins API token |
| `AI_BASE_URL` | AI model API base URL |
| `AI_MODEL` | AI model name |
| `AI_API_KEY` | AI API key |
| `SCM_ENABLED` | Enable GitHub/GitLab PR commenting |
| `SCM_PROVIDER` | `github` or `gitlab` |
| `SCM_API_URL` | SCM API URL (e.g., `https://api.github.com`) |
| `SCM_TOKEN` | Personal access token with PR write access |
| `UPDATE_JENKINS_DESCRIPTION` | Update build description with analysis |
| `POST_TO_PR` | Post analysis as PR comment |
| `SLACK_WEBHOOK_URL` | Slack webhook for notifications |
| `SERVER_API_KEY` | API key for the agent server |

## Best Practices

1. **Use API tokens**: Never use plain passwords for Jenkins authentication
2. **Secure the agent**: Use API keys and restrict network access
3. **Archive reports**: Store analysis reports as build artifacts
4. **Monitor the agent**: Check health endpoint regularly
5. **Tune the AI**: Adjust temperature and prompts for your codebase
6. **Cache results**: Use the `/results` endpoint to avoid re-analysis
