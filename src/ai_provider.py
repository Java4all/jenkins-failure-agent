"""
AI Provider abstraction layer.

Supports multiple AI backends:
- OpenAI-compatible (Ollama, vLLM, LocalAI, OpenAI)
- AWS Bedrock (Claude, Titan, Llama)
- Azure OpenAI (future)

Design: Strategy Pattern with factory method
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

logger = logging.getLogger("jenkins-agent.ai_provider")


@dataclass
class ChatMessage:
    """Unified chat message format."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass  
class ChatResponse:
    """Unified chat response format."""
    content: str
    model: str
    usage: Dict[str, int] = None  # tokens used
    raw_response: Any = None  # provider-specific raw response


class AIProvider(ABC):
    """Abstract base class for AI providers."""
    
    @abstractmethod
    def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Send chat completion request."""
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """Test if provider is reachable."""
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model name being used."""
        pass


class OpenAICompatibleProvider(AIProvider):
    """
    Provider for OpenAI-compatible APIs.
    
    Supports:
    - Ollama (default)
    - vLLM
    - LocalAI
    - OpenAI API
    - Any OpenAI-compatible endpoint
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        model: str = "llama3:8b",
        timeout: int = 120,
    ):
        from openai import OpenAI
        
        self.model = model
        self.timeout = timeout
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        logger.info(f"OpenAI-compatible provider initialized: {base_url}, model={model}")
    
    def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Send chat completion request."""
        openai_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        return ChatResponse(
            content=response.choices[0].message.content,
            model=self.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            raw_response=response,
        )
    
    def test_connection(self) -> bool:
        """Test connection to the AI model."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": "Respond with 'OK' if you can read this."}
                ],
                max_tokens=10,
            )
            return "OK" in response.choices[0].message.content.upper()
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    @property
    def model_name(self) -> str:
        return self.model


class BedrockProvider(AIProvider):
    """
    Provider for AWS Bedrock.
    
    Supports:
    - Claude 3 (Sonnet, Haiku, Opus)
    - Claude 2.x
    - Amazon Titan
    - Llama 2/3
    - Mistral
    
    Authentication (boto3 credential chain, in order of precedence):
    1. Explicit credentials passed to constructor
    2. Environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN
    3. AWS Profile: ~/.aws/credentials and ~/.aws/config
       - Supports: access keys, session tokens, SSO, MFA, assume role
       - Set profile via AWS_PROFILE env var or 'profile' parameter
    4. IAM role (for EC2/ECS/Lambda/EKS) via instance metadata
    5. Container credentials (ECS task role)
    
    AWS Profile Configuration (~/.aws/credentials):
    ------------------------------------------------
    [my-profile]
    aws_access_key_id = AKIA...
    aws_secret_access_key = ...
    aws_session_token = ...  # Optional, for temporary credentials
    
    Or with SSO (~/.aws/config):
    ----------------------------
    [profile my-sso-profile]
    sso_start_url = https://my-sso.awsapps.com/start
    sso_region = us-east-1
    sso_account_id = 123456789012
    sso_role_name = MyRole
    region = us-east-1
    
    Or with assume role (~/.aws/config):
    ------------------------------------
    [profile my-assume-role]
    role_arn = arn:aws:iam::123456789012:role/MyRole
    source_profile = default
    region = us-east-1
    
    Required IAM permissions:
    - bedrock:InvokeModel
    - bedrock:InvokeModelWithResponseStream (for streaming, future)
    """
    
    # Model ID mappings for convenience
    MODEL_ALIASES = {
        # Claude models
        "claude-3-sonnet": "anthropic.claude-3-sonnet-20240229-v1:0",
        "claude-3-haiku": "anthropic.claude-3-haiku-20240307-v1:0",
        "claude-3-opus": "anthropic.claude-3-opus-20240229-v1:0",
        "claude-3.5-sonnet": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "claude-2": "anthropic.claude-v2:1",
        "claude-instant": "anthropic.claude-instant-v1",
        # Amazon models
        "titan-express": "amazon.titan-text-express-v1",
        "titan-lite": "amazon.titan-text-lite-v1",
        # Meta models
        "llama3-8b": "meta.llama3-8b-instruct-v1:0",
        "llama3-70b": "meta.llama3-70b-instruct-v1:0",
        "llama2-13b": "meta.llama2-13b-chat-v1",
        "llama2-70b": "meta.llama2-70b-chat-v1",
        # Mistral models
        "mistral-7b": "mistral.mistral-7b-instruct-v0:2",
        "mistral-large": "mistral.mistral-large-2402-v1:0",
        "mixtral-8x7b": "mistral.mixtral-8x7b-instruct-v0:1",
    }
    
    def __init__(
        self,
        model: str = "claude-3-sonnet",
        region: str = None,
        profile: str = None,
        credentials_file: str = None,
        config_file: str = None,
        timeout: int = 120,
    ):
        """
        Initialize Bedrock provider.
        
        Args:
            model: Model ID or alias (e.g., "claude-3-sonnet", "llama3-8b")
            region: AWS region (default: from profile, env, or boto3 default)
            profile: AWS profile name from ~/.aws/credentials or ~/.aws/config
                     Supports profiles with: access keys, session tokens, SSO, 
                     MFA, assume role, etc.
            credentials_file: Custom path to AWS credentials file 
                              (default: ~/.aws/credentials)
            config_file: Custom path to AWS config file
                         (default: ~/.aws/config)
            timeout: Request timeout in seconds
        """
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError:
            raise ImportError(
                "boto3 is required for AWS Bedrock. "
                "Install with: pip install boto3"
            )
        
        # Resolve model alias to full ID
        self.model = self.MODEL_ALIASES.get(model, model)
        self.model_alias = model
        self.timeout = timeout
        
        # Configure boto3 client settings
        boto_config = BotoConfig(
            read_timeout=timeout,
            connect_timeout=30,
            retries={"max_attempts": 3},
        )
        
        # Set custom credential/config file paths if provided
        # These environment variables are read by boto3/botocore
        if credentials_file:
            os.environ['AWS_SHARED_CREDENTIALS_FILE'] = credentials_file
            logger.info(f"Using custom credentials file: {credentials_file}")
        
        if config_file:
            os.environ['AWS_CONFIG_FILE'] = config_file
            logger.info(f"Using custom config file: {config_file}")
        
        # Build session with profile support
        # Profile can include: access keys, session tokens, SSO, assume role, etc.
        session_kwargs = {}
        
        # Profile name - can be set via parameter or AWS_PROFILE env var
        effective_profile = profile or os.environ.get('AWS_PROFILE')
        if effective_profile:
            session_kwargs["profile_name"] = effective_profile
            logger.info(f"Using AWS profile: {effective_profile}")
        
        # Region - can be set via parameter, profile config, or env var
        if region:
            session_kwargs["region_name"] = region
        
        # Create session - this handles all credential types:
        # - Access keys from profile
        # - Session tokens (temporary credentials)
        # - SSO login
        # - Assume role
        # - Instance metadata (EC2/ECS/Lambda)
        try:
            session = boto3.Session(**session_kwargs)
            
            # Verify credentials are available
            credentials = session.get_credentials()
            if credentials is None:
                raise ValueError(
                    "No AWS credentials found. Configure one of:\n"
                    "  1. AWS profile in ~/.aws/credentials\n"
                    "  2. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)\n"
                    "  3. IAM role (for EC2/ECS/Lambda)\n"
                    "  4. AWS SSO (run 'aws sso login --profile <profile>')"
                )
            
            # Log credential type (without exposing secrets)
            cred_method = credentials.method if hasattr(credentials, 'method') else 'unknown'
            logger.info(f"AWS credentials loaded via: {cred_method}")
            
            # Check if using temporary credentials (has session token)
            frozen_creds = credentials.get_frozen_credentials()
            if frozen_creds.token:
                logger.info("Using temporary credentials (session token present)")
            
        except Exception as e:
            raise ValueError(f"Failed to create AWS session: {e}")
        
        # Create Bedrock client
        self.client = session.client(
            "bedrock-runtime",
            config=boto_config,
        )
        
        self.region = region or session.region_name or os.environ.get("AWS_REGION", "us-east-1")
        
        logger.info(f"Bedrock provider initialized: region={self.region}, model={self.model}")
    
    def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Send chat completion request to Bedrock."""
        
        # Determine model family for request formatting
        if "anthropic.claude" in self.model:
            return self._chat_claude(messages, temperature, max_tokens)
        elif "amazon.titan" in self.model:
            return self._chat_titan(messages, temperature, max_tokens)
        elif "meta.llama" in self.model:
            return self._chat_llama(messages, temperature, max_tokens)
        elif "mistral" in self.model:
            return self._chat_mistral(messages, temperature, max_tokens)
        else:
            # Default to Claude format
            return self._chat_claude(messages, temperature, max_tokens)
    
    def _chat_claude(
        self,
        messages: List[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> ChatResponse:
        """Claude-specific request format."""
        
        # Extract system message
        system_prompt = ""
        chat_messages = []
        
        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                chat_messages.append({
                    "role": msg.role,
                    "content": msg.content,
                })
        
        # Claude Messages API format
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat_messages,
        }
        
        if system_prompt:
            body["system"] = system_prompt
        
        response = self.client.invoke_model(
            modelId=self.model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        
        result = json.loads(response["body"].read())
        
        return ChatResponse(
            content=result["content"][0]["text"],
            model=self.model,
            usage={
                "prompt_tokens": result.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": result.get("usage", {}).get("output_tokens", 0),
            },
            raw_response=result,
        )
    
    def _chat_titan(
        self,
        messages: List[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> ChatResponse:
        """Amazon Titan-specific request format."""
        
        # Combine messages into single prompt
        prompt_parts = []
        for msg in messages:
            if msg.role == "system":
                prompt_parts.append(f"Instructions: {msg.content}")
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")
        
        prompt_parts.append("Assistant:")
        prompt = "\n\n".join(prompt_parts)
        
        body = {
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": temperature,
                "topP": 0.9,
            },
        }
        
        response = self.client.invoke_model(
            modelId=self.model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        
        result = json.loads(response["body"].read())
        
        return ChatResponse(
            content=result["results"][0]["outputText"],
            model=self.model,
            usage={
                "prompt_tokens": result.get("inputTextTokenCount", 0),
                "completion_tokens": result["results"][0].get("tokenCount", 0),
            },
            raw_response=result,
        )
    
    def _chat_llama(
        self,
        messages: List[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> ChatResponse:
        """Meta Llama-specific request format."""
        
        # Format messages for Llama
        prompt_parts = []
        system_content = ""
        
        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            elif msg.role == "user":
                prompt_parts.append(f"[INST] {msg.content} [/INST]")
            elif msg.role == "assistant":
                prompt_parts.append(msg.content)
        
        if system_content:
            prompt = f"<<SYS>>\n{system_content}\n<</SYS>>\n\n" + "\n".join(prompt_parts)
        else:
            prompt = "\n".join(prompt_parts)
        
        body = {
            "prompt": prompt,
            "max_gen_len": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
        }
        
        response = self.client.invoke_model(
            modelId=self.model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        
        result = json.loads(response["body"].read())
        
        return ChatResponse(
            content=result["generation"],
            model=self.model,
            usage={
                "prompt_tokens": result.get("prompt_token_count", 0),
                "completion_tokens": result.get("generation_token_count", 0),
            },
            raw_response=result,
        )
    
    def _chat_mistral(
        self,
        messages: List[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> ChatResponse:
        """Mistral-specific request format."""
        
        # Format messages for Mistral
        prompt_parts = []
        
        for msg in messages:
            if msg.role == "system":
                prompt_parts.append(f"<s>[INST] {msg.content}")
            elif msg.role == "user":
                if prompt_parts:
                    prompt_parts.append(f" {msg.content} [/INST]")
                else:
                    prompt_parts.append(f"<s>[INST] {msg.content} [/INST]")
            elif msg.role == "assistant":
                prompt_parts.append(f" {msg.content}</s>")
        
        prompt = "".join(prompt_parts)
        
        body = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
        }
        
        response = self.client.invoke_model(
            modelId=self.model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        
        result = json.loads(response["body"].read())
        
        return ChatResponse(
            content=result["outputs"][0]["text"],
            model=self.model,
            usage={},  # Mistral doesn't return token counts
            raw_response=result,
        )
    
    def test_connection(self) -> bool:
        """Test connection to Bedrock."""
        try:
            response = self.chat(
                messages=[
                    ChatMessage(role="user", content="Respond with 'OK' if you can read this.")
                ],
                max_tokens=10,
            )
            return "OK" in response.content.upper()
        except Exception as e:
            logger.error(f"Bedrock connection test failed: {e}")
            return False
    
    @property
    def model_name(self) -> str:
        return self.model_alias


# =============================================================================
# Factory Function
# =============================================================================

def create_ai_provider(
    provider: str = "openai_compatible",
    **kwargs,
) -> AIProvider:
    """
    Factory function to create AI provider.
    
    Args:
        provider: Provider type
            - "openai_compatible" (default): Ollama, vLLM, OpenAI, LocalAI
            - "bedrock": AWS Bedrock
            - "azure" (future): Azure OpenAI
        **kwargs: Provider-specific configuration
    
    Examples:
        # Local Ollama
        provider = create_ai_provider(
            provider="openai_compatible",
            base_url="http://localhost:11434/v1",
            model="llama3:8b",
        )
        
        # AWS Bedrock with Claude
        provider = create_ai_provider(
            provider="bedrock",
            model="claude-3-sonnet",
            region="us-east-1",
        )
        
        # AWS Bedrock with Llama
        provider = create_ai_provider(
            provider="bedrock",
            model="llama3-70b",
        )
    
    Returns:
        AIProvider instance
    """
    provider = provider.lower()
    
    if provider in ("openai_compatible", "openai", "ollama", "vllm", "localai"):
        return OpenAICompatibleProvider(
            base_url=kwargs.get("base_url", "http://localhost:11434/v1"),
            api_key=kwargs.get("api_key", "ollama"),
            model=kwargs.get("model", "llama3:8b"),
            timeout=kwargs.get("timeout", 120),
        )
    
    elif provider == "bedrock":
        return BedrockProvider(
            model=kwargs.get("model", "claude-3-sonnet"),
            region=kwargs.get("region"),
            profile=kwargs.get("profile"),
            credentials_file=kwargs.get("credentials_file"),
            config_file=kwargs.get("config_file"),
            timeout=kwargs.get("timeout", 120),
        )
    
    else:
        raise ValueError(
            f"Unknown AI provider: {provider}. "
            f"Supported: openai_compatible, bedrock"
        )


def get_provider_from_config(ai_config) -> AIProvider:
    """
    Create AI provider from AIConfig dataclass.
    
    Args:
        ai_config: AIConfig instance from config.py
    
    Returns:
        AIProvider instance
    """
    return create_ai_provider(
        provider=ai_config.provider,
        base_url=ai_config.base_url,
        api_key=ai_config.api_key,
        model=ai_config.model,
        timeout=ai_config.timeout,
        # Bedrock-specific (from config or env)
        region=getattr(ai_config, 'region', None) or os.environ.get('AWS_REGION'),
        profile=getattr(ai_config, 'profile', None) or os.environ.get('AWS_PROFILE'),
        credentials_file=getattr(ai_config, 'credentials_file', None) or os.environ.get('AWS_SHARED_CREDENTIALS_FILE'),
        config_file=getattr(ai_config, 'config_file', None) or os.environ.get('AWS_CONFIG_FILE'),
    )
